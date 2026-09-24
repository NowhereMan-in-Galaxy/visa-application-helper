"""specs/002 "状态计算"：六种需求状态、ask_if、下一步、进度，以及 Track 的读写。"""

from datetime import date

from config import COMMUNITY_DIR
from core.guides import load_guide
from core.material_types import load_vocabulary
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


# ---- 材料齐了自动完成 ----

def test_step_auto_done_when_its_required_materials_are_ready():
    v = view({"matches": {"r-bank": ["b"]}}, records=[rec("b", "银行流水")])
    s = step(v, "s-bank")
    assert s.done and s.auto_done  # r-extra 是加分项，不影响
    assert v.next_step == "s-docs"


def test_unconfirmed_material_does_not_auto_complete():
    v = view(records=[rec("b", "银行流水")])
    assert req(v, "r-bank").state == "unconfirmed"
    assert not step(v, "s-bank").done


def test_undecided_material_blocks_auto_complete():
    records = [rec("p1", "护照个人信息页"), rec("p2", "护照签证页")]
    v = view({"matches": {"r-passport": ["p1", "p2"]}}, records=records)
    assert req(v, "r-kinship").state == "undecided"
    assert not step(v, "s-docs").done
    v = view({"facts": {"sponsored": "否"}, "matches": {"r-passport": ["p1", "p2"]}}, records=records)
    assert step(v, "s-docs").auto_done


def test_later_step_reusing_a_material_is_not_auto_done():
    data = make_guide().model_dump(by_alias=True, exclude_none=True)
    data["steps"][3]["requirements"] = ["r-bank"]  # 递交时"带着流水去"：流水齐了不代表递交做完了
    guide = make_guide(steps=data["steps"])
    track = Track(id="t", guide=guide.id, title="t", created=TODAY, matches={"r-bank": ["b"]})
    v = compute_track_view(guide, track, [rec("b", "银行流水")], VOCAB, TODAY)
    assert step(v, "s-bank").auto_done
    assert not step(v, "s-submit").done


def test_manually_done_step_is_not_marked_auto():
    v = view({"done_steps": ["s-bank"], "matches": {"r-bank": ["b"]}}, records=[rec("b", "银行流水")])
    assert step(v, "s-bank").done and not step(v, "s-bank").auto_done


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


# ---- 办完与用时 ----

from core.tracks import is_track_complete, sync_completion  # noqa: E402


def test_complete_when_all_applicable_steps_done():
    v = view({"facts": {"identity": "学生"}, "done_steps": ["s-bank", "s-docs", "s-submit"]})
    assert is_track_complete(v)


def test_not_complete_while_a_step_is_undecided():
    v = view({"done_steps": ["s-bank", "s-docs", "s-submit"]})  # s-job 还取决于"身份"
    assert not is_track_complete(v)


def test_sync_completion_records_first_day_and_clears_on_undo():
    guide = make_guide()
    track = Track(id="t", guide=guide.id, title="t", created=date(2026, 9, 1),
                  facts={"identity": "学生"}, done_steps=["s-bank", "s-docs", "s-submit"])
    sync_completion(track, compute_track_view(guide, track, [], VOCAB, TODAY), TODAY)
    assert track.completed == TODAY
    later = date(2026, 10, 1)
    sync_completion(track, compute_track_view(guide, track, [], VOCAB, later), later)
    assert track.completed == TODAY  # 已经记过的日期不会被后来的保存改掉
    assert compute_track_view(guide, track, [], VOCAB, later).elapsed_days == 22
    track.done_steps = ["s-bank"]
    sync_completion(track, compute_track_view(guide, track, [], VOCAB, later), later)
    assert track.completed is None


# ---- 倒排时间（spec 002 Phase C 第一条，见 specs/002-guide-to-track/spec.md "状态计算"）----


def test_no_deadline_means_all_null():
    v = view({"facts": {"identity": "在职"}})
    assert all(s.latest_start is None and s.late is False for s in v.steps)
    assert all(p.latest_finish is None for p in v.phases)


def test_transitive_dependency_chain_propagates_backwards():
    # s-submit depends_on [s-bank, s-job, s-docs]，duration_days max=20；三者本身没有时长
    v = view({"facts": {"identity": "在职"}, "deadline": date(2026, 10, 10)})
    assert step(v, "s-submit").latest_start == date(2026, 9, 20)  # 2026-10-10 减 20 天
    # 直接依赖 s-submit 的步骤，latest_finish 等于 s-submit 的 latest_start；自身没有时长，latest_start 相同
    assert step(v, "s-bank").latest_start == date(2026, 9, 20)
    assert step(v, "s-job").latest_start == date(2026, 9, 20)
    assert step(v, "s-docs").latest_start == date(2026, 9, 20)


def test_step_with_no_dependents_uses_deadline_as_latest_finish():
    v = view({"facts": {"identity": "在职"}, "deadline": date(2026, 10, 10)})
    assert step(v, "s-submit").latest_start == date(2026, 9, 20)


def test_completed_step_excluded_from_deadline_calc():
    v = view({"facts": {"identity": "在职"}, "deadline": date(2026, 10, 10), "done_steps": ["s-submit"]})
    # s-submit 已完成，不再计入 S；s-bank 因此不再被它约束，直接用 deadline 当 latest_finish（自身无时长）
    assert step(v, "s-submit").latest_start is None
    assert step(v, "s-bank").latest_start == date(2026, 10, 10)


def test_late_when_today_past_latest_start():
    v = view({"facts": {"identity": "在职"}, "deadline": date(2026, 10, 10)}, records=())
    # latest_start(s-bank) == 2026-09-20，TODAY 是 2026-09-23，已经晚了
    assert step(v, "s-bank").late is True
    # s-wait 之类不适用的步骤没有 available，late 恒为 False（这份攻略没有 s-wait，用 s-job 佐证不适用步骤不受影响）
    v2 = view({"facts": {"identity": "学生"}, "deadline": date(2026, 10, 10)})
    assert step(v2, "s-job").applies == "no"
    assert step(v2, "s-job").latest_start is None and step(v2, "s-job").late is False


def test_not_late_when_today_before_latest_start():
    v = view({"facts": {"identity": "在职"}, "deadline": date(2026, 12, 1)})
    assert step(v, "s-submit").late is False


def test_undecided_step_excluded_from_deadline_calc():
    # identity 没回答时 s-job 是 undecided（不是 yes），不计入集合 S
    v = view({"deadline": date(2026, 10, 10)})
    assert step(v, "s-job").applies == "undecided"
    assert step(v, "s-job").latest_start is None


def test_phase_latest_finish_is_max_of_its_steps():
    v = phased_view({"facts": {"identity": "学生"}, "deadline": date(2026, 10, 10)})
    prep, go = v.phases
    # p-go 只有 s-submit（没人依赖它）：latest_finish = deadline
    assert go.latest_finish == date(2026, 10, 10)
    # p-prep 里 s-bank / s-docs 都是 s-submit 的依赖（s-job 因"学生"身份不适用，不计入）
    assert prep.latest_finish == date(2026, 9, 20)


def test_phase_latest_finish_null_when_no_pending_steps_in_phase():
    v = phased_view({"facts": {"identity": "学生"}, "deadline": date(2026, 10, 10), "done_steps": ["s-bank", "s-docs"]})
    prep, go = v.phases
    assert prep.latest_finish is None
    assert go.latest_finish == date(2026, 10, 10)


# ---- 倒排时间：申根真实攻略（specs/002-guide-to-track/tasks-parallel-1.md 任务 D 的例子）----


def _schengen_view(deadline, today=TODAY):
    vocab = load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    result = load_guide(COMMUNITY_DIR / "guides" / "schengen-tourist.yaml", vocab)
    assert result.valid, result.errors
    track = Track(id="t", guide=result.guide.id, title="t", created=today, deadline=deadline)
    return compute_track_view(result.guide, track, [], vocab, today)


def test_schengen_deadline_example_from_spec():
    v = _schengen_view(date(2026, 12, 1))
    wait = next(s for s in v.steps if s.id == "s-wait")
    submit = next(s for s in v.steps if s.id == "s-submit")
    assert wait.latest_start == date(2026, 10, 17)  # deadline 减 duration_days.max=45
    assert submit.latest_start == date(2026, 10, 17)  # s-wait 是它唯一的直接依赖，latest_finish 等于 latest_start


def test_schengen_wait_phase_latest_finish_equals_deadline():
    v = _schengen_view(date(2026, 12, 1))
    wait_phase = next(p for p in v.phases if p.id == "p-wait")
    assert wait_phase.latest_finish == date(2026, 12, 1)


# ---- 长期资料 vs 本次专用 ----

def test_one_off_record_only_matches_its_own_track():
    other = rec("b-other", "银行流水", for_track="another-track")
    mine = rec("b-mine", "银行流水", obtained=date(2026, 9, 2), for_track="t")
    v = view(records=[other])
    assert req(v, "r-bank").state == "missing"  # 别的办事专用的流水不会被匹配过来
    v = view(records=[other, mine])
    assert [c.id for c in req(v, "r-bank").records] == ["b-mine"]  # 自己这件办事的可以


def test_default_keep_follows_vocabulary_reusable():
    from core.material_types import build_vocabulary
    from core.tracks import _default_keep
    vocab = build_vocabulary({"types": [
        {"key": "bank_statement", "name": "银行流水", "aliases": []},
        {"key": "itinerary", "name": "行程单", "aliases": [], "reusable": False},
    ]})
    assert _default_keep("bank_statement", vocab) is True
    assert _default_keep("itinerary", vocab) is False
    assert _default_keep(None, vocab) is False  # 词表不认识的默认只属于这件办事
