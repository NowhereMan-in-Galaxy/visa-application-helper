"""步骤的可办时间窗和提醒（specs/002-guide-to-track/spec.md §3c，"时间提醒型"攻略）。

纯函数，不看系统时钟：`today` 一律作为参数传入。

和倒排时间（core.tracks._deadline_times）方向相反：倒排是"从截止日往回推最晚哪天开始"，
时间窗是"从某个个人日期（毕业日期、首次参保日期、上一步勾完的日期）往后数"。
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

from core.guides import DateRef, Guide, Step

WindowState = Literal["waiting", "upcoming", "open", "closing", "missed"]
# 距截止不超过这么多天时，状态从 open 变成 closing（界面标红"只剩 N 天"）
CLOSING_SOON_DAYS = 30
# 日历里的截止事件提前这么多天提醒
CALENDAR_ALARM_DAYS = 7
# "可以办了"事件当天几点提醒（全天事件的提醒相对当天 0 点）
CALENDAR_OPENS_ALARM_HOUR = 9


def add_months(d: date, months: int) -> date:
    """加 N 个月；日子超出当月天数时取当月最后一天（1 月 31 日 + 1 个月 = 2 月 28/29 日）。"""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def resolve(ref: DateRef, facts: dict[str, str], done_on: dict[str, date]) -> date | None:
    """算出日期引用指向的那一天；基准未知（问题没回答、步骤没勾或没有勾选日期）时返回 None。"""
    if ref.fact is not None:
        raw = facts.get(ref.fact)
        try:
            base = date.fromisoformat(raw) if raw else None
        except ValueError:
            base = None  # 手改 Track 文件写坏了日期，按"没回答"处理，不让整个页面报错
    else:
        base = done_on.get(ref.step)
    if base is None:
        return None
    d = add_months(base, ref.months) + timedelta(days=ref.days)
    if ref.end_of == "month":
        d = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    elif ref.end_of == "year":
        d = date(d.year, 12, 31)
    return d


def _missing(ref: DateRef) -> str:
    return ref.fact if ref.fact is not None else ref.step


def window_view(step: Step, facts: dict[str, str], done_on: dict[str, date], today: date) -> dict | None:
    """StepView.window：{opens, closes, state, days, waiting_for}；步骤没写 window 时为 None。"""
    w = step.window
    if w is None:
        return None
    opens = resolve(w.opens, facts, done_on) if w.opens else None
    closes = resolve(w.closes, facts, done_on) if w.closes else None
    waiting_for = [_missing(r) for r, d in ((w.opens, opens), (w.closes, closes)) if r is not None and d is None]

    state: WindowState
    days: int | None = None
    if closes is not None and today > closes:
        state = "missed"
    elif w.opens is not None and opens is None:
        state = "waiting"
    elif opens is not None and today < opens:
        state, days = "upcoming", (opens - today).days
    elif closes is not None and (closes - today).days <= CLOSING_SOON_DAYS:
        state, days = "closing", (closes - today).days
    else:
        state = "open"
        days = (closes - today).days if closes is not None else None
    return {
        "opens": opens.isoformat() if opens else None,
        "closes": closes.isoformat() if closes else None,
        "state": state, "days": days, "waiting_for": waiting_for,
    }


def reminders(guide: Guide, step_views: list, today: date) -> list[dict]:
    """TrackView.reminders：生效、未完成、未隐藏的步骤里，以后会"开始可以办"或"截止"的日子，按日期排序。"""
    titles = {s.id: s.title for s in guide.steps}
    out = []
    for sv in step_views:
        if sv.applies != "yes" or sv.done or sv.hidden or not sv.window:
            continue
        opens, closes = sv.window["opens"], sv.window["closes"]
        if opens and date.fromisoformat(opens) > today:
            out.append({"date": opens, "kind": "opens", "step": sv.id, "title": titles.get(sv.id, sv.title)})
        if closes and date.fromisoformat(closes) >= today:
            out.append({"date": closes, "kind": "closes", "step": sv.id, "title": titles.get(sv.id, sv.title)})
    out.sort(key=lambda r: (r["date"], r["kind"] != "opens"))
    return out


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def calendar_ics(track_id: str, track_title: str, items: list[dict], now_stamp: str) -> str:
    """把提醒写成 iCalendar 文本（手机/电脑日历都能导入）。每条提醒一个全天事件。

    `now_stamp` 形如 20260923T120000Z，由调用方传入（保持纯函数）。UID 固定，重复导入同一件办事不会出现重复事件。
    """
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//youtiaoyouli//reminders//ZH",
        "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_ics_escape(track_title)}",
    ]
    for r in items:
        day = date.fromisoformat(r["date"])
        prefix = "可以办了" if r["kind"] == "opens" else "截止"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{track_id}-{r['step']}-{r['kind']}@youtiaoyouli",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(prefix + '：' + r['title'])}",
            f"DESCRIPTION:{_ics_escape(track_title)}",
        ]
        if r["kind"] == "closes":
            trigger, alarm = f"-P{CALENDAR_ALARM_DAYS}D", f"还有 {CALENDAR_ALARM_DAYS} 天截止：{r['title']}"
        else:
            trigger, alarm = f"PT{CALENDAR_OPENS_ALARM_HOUR}H", f"今天起可以办：{r['title']}"
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{trigger}", f"DESCRIPTION:{_ics_escape(alarm)}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    # iCalendar 规定用 CRLF 换行，每行不超过 75 字节（超过的折到下一行，下一行以空格开头）
    return "".join(_fold(line) + "\r\n" for line in lines)


def _fold(line: str, limit: int = 75) -> str:
    """按 RFC 5545 折行：按 UTF-8 字节数切，不把一个汉字切成两半。"""
    parts, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        # 续行开头的空格也算 1 字节
        if size + n > (limit if not parts else limit - 1):
            parts.append(current)
            current, size = "", 0
        current += ch
        size += n
    parts.append(current)
    return "\r\n ".join(parts)
