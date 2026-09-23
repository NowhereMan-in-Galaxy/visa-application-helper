"""specs/002 "状态计算"：六种需求状态、ask_if、下一步、进度，以及 Track 的读写。"""

from datetime import date

from core.models import MaterialCategory, MaterialRecord
from core.tracks import Track, compute_track_view, create_track, load_track, save_track

from guide_fixtures import VOCAB, make_guide

TODAY = date(2026, 9, 23)


def rec(id, type, obtained=date(2026, 9, 1), **kw) -> MaterialRecord:
    return MaterialRecord(id=id, category=MaterialCategory.FINANCIAL_SNAPSHOT, type=type, obtained_date=obtained, **kw)


def view(track_kwargs=None, records=()):
    guide = make_guide()
    track = Track(id="t", guide=guide.id, title="t", created=TODAY, **(track_kwargs or {}))
    return compute_track_view(guide, track, list(records), VOCAB, TODAY)


def req(v, rid):
    return next(r for r in v.requirements if r.id == rid)


def step(v, sid):
    return next(s for s in v.steps if s.id == sid)


# ---- 六种需求状态 ----

def test_not_applicable_when_condition_fails():
    assert req(view({"facts": {"identity": "学生"}}), "r-job").state == "not_applicable"


def test_undecided_when_fact_unanswered():
    assert req(view(), "r-job").state == "undecided"


def test_missing_when_no_record():
    assert req(view(), "r-bank").state == "missing"


def test_missing_when_composite_lacks_a_part():
    v = view(records=[rec("bio", "护照个人信息页")])
    r = req(v, "r-passport")
    assert r.state == "missing"
    assert r.missing_parts == [{"key": "passport_visa_page", "name": "护照签证页"}]


def test_placeholder_record_without_date_does_not_count():
    assert req(view(records=[rec("b", "银行流水", obtained=None)]), "r-bank").state == "missing"


def test_stale_when_older_than_freshness_days():
    assert req(view(records=[rec("b", "银行流水", obtained=date(2026, 8, 1))]), "r-bank").state == "stale"


def test_stale_when_record_expired():
    old = rec("b", "银行流水", obtained=date(2026, 9, 20), validity_days=1)
    assert req(view(records=[old]), "r-bank").state == "stale"


def test_unconfirmed_when_candidate_exists():
    r = req(view(records=[rec("b", "银行流水")]), "r-bank")
    assert r.state == "unconfirmed"
    assert [c.id for c in r.records] == ["b"]


def test_ready_when_confirmed():
    v = view({"matches": {"r-bank": ["b"]}}, records=[rec("b", "银行流水")])
    assert req(v, "r-bank").state == "ready"


def test_confirmed_match_to_deleted_record_falls_back_to_candidates():
    v = view({"matches": {"r-bank": ["gone"]}}, records=[rec("b", "银行流水")])
    assert req(v, "r-bank").state == "unconfirmed"


def test_composite_candidates_take_one_record_per_part():
    v = view(records=[rec("bio", "护照个人信息页"), rec("visa", "护照签证页")])
    assert [c.id for c in req(v, "r-passport").records] == ["bio", "visa"]


def test_latest_record_is_the_candidate():
    v = view(records=[rec("old", "银行流水", obtained=date(2026, 9, 1)), rec("new", "银行流水", obtained=date(2026, 9, 20))])
    assert [c.id for c in req(v, "r-bank").records] == ["new"]


def test_example_records_are_never_candidates():
    assert req(view(records=[rec("example-bank", "银行流水")]), "r-bank").state == "missing"


def test_raw_name_resolved_through_vocabulary():
    r = req(view(), "r-extra")  # raw_name "银行流水原件" 规范化后命中 bank_statement
    assert r.material_type == "bank_statement" and not r.type_unresolved


def test_unresolved_raw_name_is_flagged():
    v = view({"facts": {"sponsored": "是", "same_hukou": "否"}})
    r = req(v, "r-kinship")
    assert r.state == "missing" and r.type_unresolved


# ---- ask_if ----

def test_fact_not_asked_until_parent_answered():
    facts = {f.key: f for f in view().facts}
    assert facts["sponsored"].asked and not facts["same_hukou"].asked
    assert req(view(), "r-kinship").state == "undecided"


def test_ask_if_unmet_makes_dependent_requirement_not_applicable():
    v = view({"facts": {"sponsored": "否"}})
    assert not next(f for f in v.facts if f.key == "same_hukou").asked
    assert req(v, "r-kinship").state == "not_applicable"


def test_ask_if_met_asks_the_question():
    v = view({"facts": {"sponsored": "是"}})
    assert next(f for f in v.facts if f.key == "same_hukou").asked
    assert req(v, "r-kinship").state == "undecided"


# ---- 下一步 ----

def test_next_step_without_dependencies_is_first_available():
    assert view().next_step == "s-bank"


def test_step_with_unfinished_dependency_not_available():
    v = view({"facts": {"identity": "在职"}, "done_steps": ["s-bank", "s-docs"]})
    assert v.next_step == "s-job"
    assert not step(v, "s-submit").available


def test_dependency_on_non_applicable_step_counts_as_satisfied():
    v = view({"facts": {"identity": "学生"}, "done_steps": ["s-bank", "s-docs"]})
    assert step(v, "s-job").applies == "no"
    assert v.next_step == "s-submit"


def test_no_next_step_when_all_done():
    v = view({"facts": {"identity": "学生"}, "done_steps": ["s-bank", "s-docs", "s-submit"]})
    assert v.next_step is None


# ---- 进度 ----

def test_progress_excludes_optional_and_unapplicable():
    v = view({"facts": {"identity": "学生", "sponsored": "否"}, "matches": {"r-bank": ["b"]}}, records=[rec("b", "银行流水")])
    # 计入：r-bank（ready）、r-passport（missing）；不计：r-job（不适用）、r-kinship（不适用）、r-extra（optional）
    assert (v.progress_ready, v.progress_total) == (1, 2)


def test_stale_source_flagged():
    guide = make_guide(sources=[{"id": "g1", "title": "旧资料", "as_of": "2024-01-01"}])
    track = Track(id="t", guide=guide.id, title="t", created=TODAY)
    assert compute_track_view(guide, track, [], VOCAB, TODAY).stale_sources == ["g1"]


# ---- 读写（个人区） ----

def test_create_track_never_overwrites(tmp_path):
    guide = make_guide()
    first = create_track(tmp_path, guide, TODAY)
    second = create_track(tmp_path, guide, TODAY)
    assert first.id == "demo-guide-20260923"
    assert second.id == "demo-guide-20260923-2"


def test_track_round_trip(tmp_path):
    track = Track(id="x", guide="demo-guide", title="我的", created=TODAY, facts={"identity": "在职"}, done_steps=["s-bank"])
    save_track(tmp_path, track)
    assert load_track(tmp_path, "x") == track


def test_track_ignores_ids_removed_from_guide():
    v = view({"facts": {"gone_fact": "x"}, "done_steps": ["s-gone"], "done_checks": ["c-gone"]})
    assert v.next_step == "s-bank"


# ---- 阶段状态 ----

def phased_view(track_kwargs):
    from test_guides import with_phases
    from core.guides import Guide
    guide = Guide.model_validate(with_phases())
    track = Track(id="t", guide=guide.id, title="t", created=TODAY, **track_kwargs)
    return compute_track_view(guide, track, [], VOCAB, TODAY)


def test_phase_states_follow_next_step():
    v = phased_view({"facts": {"identity": "学生"}})
    assert [(p.id, p.state) for p in v.phases] == [("p-prep", "current"), ("p-go", "upcoming")]


def test_phase_done_when_all_applicable_steps_done():
    v = phased_view({"facts": {"identity": "学生"}, "done_steps": ["s-bank", "s-docs"]})
    prep = v.phases[0]
    assert prep.state == "done" and (prep.steps_done, prep.steps_total) == (2, 2)  # s-job 不适用，不计
    assert v.phases[1].state == "current"
