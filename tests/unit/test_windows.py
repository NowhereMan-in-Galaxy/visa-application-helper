"""specs/002 §3c：日期类问题、步骤的可办时间窗、提醒和日历导出。日期全部虚构。"""

from datetime import date

import pytest

from core.guides import DateRef, Guide, validate_guide
from core.tracks import Track, compute_track_view, set_fact_value, set_step_done
from core.windows import add_months, calendar_ics, resolve
from guide_fixtures import VOCAB, guide_dict

EV = [{"source": "g1", "quote": "原话"}]


def timed_guide(**changes) -> dict:
    """在最小攻略上加两个日期问题和三个带时间窗的步骤：报名（开始日 +1 月起）、申请（+6 月起，毕业 +24 月止）、复领（报名勾完 +12 月起）。"""
    d = guide_dict()
    d["facts"]["grad"] = {"question": "毕业日期？", "type": "date"}
    d["facts"]["start"] = {"question": "开始日期？", "type": "date"}
    d["steps"] += [
        {"id": "s-join", "title": "报名", "window": {"opens": {"fact": "start", "months": 1}}, "evidence": EV},
        {"id": "s-apply", "title": "申请", "evidence": EV,
         "window": {"opens": {"fact": "start", "months": 6}, "closes": {"fact": "grad", "months": 24}}},
        {"id": "s-again", "title": "复领", "depends_on": ["s-join"], "evidence": EV,
         "window": {"opens": {"step": "s-join", "months": 12}}},
    ]
    d.update(changes)
    return d


def view(track: Track, today: date, d: dict | None = None):
    return compute_track_view(Guide.model_validate(d or timed_guide()), track, [], VOCAB, today)


def step(v, sid):
    return next(s for s in v.steps if s.id == sid)


# ---- 日期计算 ----

def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_resolve_offsets_and_end_of():
    facts = {"start": "2026-07-01"}
    assert resolve(DateRef(fact="start", months=12), facts, {}) == date(2027, 7, 1)
    # 就业补贴的"次年年底"：首次参保 + 24 个月所在年份的 12 月 31 日
    assert resolve(DateRef(fact="start", months=24, end_of="year"), facts, {}) == date(2028, 12, 31)
    assert resolve(DateRef(fact="start", days=-1, end_of="month"), facts, {}) == date(2026, 6, 30)
    assert resolve(DateRef(step="s-join", months=12), facts, {"s-join": date(2026, 9, 1)}) == date(2027, 9, 1)
    assert resolve(DateRef(fact="grad"), facts, {}) is None
    assert resolve(DateRef(fact="start"), {"start": "坏日期"}, {}) is None


# ---- 时间窗状态 ----

def test_window_waiting_until_date_answered():
    v = view(Track(id="t", guide="demo-guide", title="t", created=date(2026, 9, 1)), date(2026, 9, 23))
    w = step(v, "s-apply").window
    assert w["state"] == "waiting" and set(w["waiting_for"]) == {"start", "grad"}
    assert step(v, "s-apply").available  # 基准未知时不挡"下一步"，先提示回答
    assert step(v, "s-bank").window is None  # 没写 window 的步骤不受影响


def test_window_states_over_time():
    t = Track(id="t", guide="demo-guide", title="t", created=date(2026, 7, 1),
              facts={"start": "2026-07-01", "grad": "2026-06-30"})
    before = step(view(t, date(2026, 9, 23)), "s-apply")
    assert before.window["state"] == "upcoming" and before.window["opens"] == "2027-01-01"
    assert before.window["days"] == (date(2027, 1, 1) - date(2026, 9, 23)).days
    assert not before.available

    assert step(view(t, date(2027, 3, 1)), "s-apply").window["state"] == "open"
    closing = step(view(t, date(2028, 6, 10)), "s-apply").window
    assert closing["state"] == "closing" and closing["days"] == 20 and closing["closes"] == "2028-06-30"
    assert step(view(t, date(2028, 6, 30)), "s-apply").window["days"] == 0
    missed = step(view(t, date(2028, 7, 1)), "s-apply")
    assert missed.window["state"] == "missed" and not missed.available


def test_window_from_previous_step_done_date():
    t = Track(id="t", guide="demo-guide", title="t", created=date(2026, 7, 1), facts={"start": "2026-07-01"})
    assert step(view(t, date(2026, 9, 23)), "s-again").window["waiting_for"] == ["s-join"]
    set_step_done(t, "s-join", True, date(2026, 9, 23))
    assert t.done_on["s-join"] == date(2026, 9, 23)
    again = step(view(t, date(2026, 9, 24)), "s-again")
    assert again.window["state"] == "upcoming" and again.window["opens"] == "2027-09-23"
    assert step(view(t, date(2026, 9, 24)), "s-join").window is None  # 做完的步骤不再算时间窗
    set_step_done(t, "s-join", False, date(2026, 9, 24))
    assert "s-join" not in t.done_on


def test_next_step_skips_steps_not_yet_open():
    d = timed_guide()
    d["steps"] = [s for s in d["steps"] if s["id"] in ("s-join", "s-apply")]
    d["requirements"], d["checks"] = [], []
    t = Track(id="t", guide="demo-guide", title="t", created=date(2026, 7, 1),
              facts={"start": "2026-07-01", "grad": "2026-06-30"})
    assert view(t, date(2026, 7, 15), d).next_step is None  # 两步都还没到时间
    assert view(t, date(2026, 8, 1), d).next_step == "s-join"


def test_reminders_sorted_and_calendar():
    t = Track(id="t", guide="demo-guide", title="我的补贴", created=date(2026, 7, 1),
              facts={"start": "2026-07-01", "grad": "2026-06-30"})
    v = view(t, date(2026, 7, 15))
    assert [(r["date"], r["kind"], r["step"]) for r in v.reminders] == [
        ("2026-08-01", "opens", "s-join"),
        ("2027-01-01", "opens", "s-apply"),
        ("2028-06-30", "closes", "s-apply"),
    ]
    ics = calendar_ics(t.id, v.title, v.reminders, "20260715T000000Z")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 3 and ics.count("BEGIN:VALARM") == 3
    assert "TRIGGER:-P7D" in ics and "TRIGGER:PT9H" in ics
    assert "DTSTART;VALUE=DATE:20280630" in ics and "SUMMARY:截止：申请" in ics
    assert "UID:t-s-apply-closes@youtiaoyouli" in ics


def test_calendar_folds_long_lines():
    title = "申请一项名字非常非常长的补贴" * 5
    ics = calendar_ics("t", "t", [{"date": "2027-01-01", "kind": "opens", "step": "s", "title": title}], "20260101T000000Z")
    lines = ics.split("\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:可以办了：" + title in unfolded


# ---- 回答日期问题 ----

def test_set_fact_value_checks_date_format():
    g = Guide.model_validate(timed_guide())
    t = Track(id="t", guide="demo-guide", title="t", created=date(2026, 7, 1))
    set_fact_value(g, t, "grad", "2026-06-30")
    assert t.facts["grad"] == "2026-06-30"
    for bad in ("2026/06/30", "明年", "2026-6-30"):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            set_fact_value(g, t, "grad", bad)
    with pytest.raises(ValueError, match="选项"):
        set_fact_value(g, t, "identity", "2026-06-30")


# ---- 校验 ----

def errors_of(d: dict) -> list[str]:
    return validate_guide(Guide.model_validate(d), VOCAB, file_stem="demo-guide")


def test_timed_guide_is_valid():
    assert errors_of(timed_guide()) == []


def test_date_fact_rules():
    d = timed_guide(); d["facts"]["grad"]["options"] = ["x"]
    assert any("日期类问题不写 options" in e for e in errors_of(d))
    d = timed_guide(); d["steps"][0]["applies_if"] = [{"fact": "grad", "in": ["2026-06-30"]}]
    assert any("不能引用日期类问题" in e for e in errors_of(d))


def test_window_rules():
    d = timed_guide(); d["steps"][-1]["window"] = {}
    assert any("至少写一个" in e for e in errors_of(d))
    d = timed_guide(); d["steps"][-1]["window"] = {"opens": {"fact": "start", "step": "s-join"}}
    assert any("二选一" in e for e in errors_of(d))
    d = timed_guide(); d["steps"][-1]["window"] = {"opens": {"fact": "identity"}}
    assert any("不是日期类问题" in e for e in errors_of(d))
    d = timed_guide(); d["steps"][-1]["window"] = {"opens": {"step": "s-bank"}}
    assert any("必须写在 depends_on 里" in e for e in errors_of(d))

