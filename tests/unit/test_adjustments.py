"""specs/002 个人调整：隐藏 / 备注 / 自己加步骤和材料（core/adjustments.py + apply_adjustments）。"""

from datetime import date

import pytest

import core.adjustments as adj
from core.adjustments import AdjustmentError
from core.models import MaterialCategory, MaterialRecord
from core.tracks import Track, compute_track_view

from guide_fixtures import VOCAB, make_guide
from test_guides import with_phases

TODAY = date(2026, 9, 23)


def phased():
    from core.guides import Guide
    return Guide.model_validate(with_phases())


def new_track(**kw):
    return Track(id="t", guide="demo-guide", title="t", created=TODAY, **kw)


def view(guide, track, records=()):
    return compute_track_view(guide, track, list(records), VOCAB, TODAY)


def step(v, sid):
    return next(s for s in v.steps if s.id == sid)


def req(v, rid):
    return next(r for r in v.requirements if r.id == rid)


def test_hidden_step_is_not_next_and_listed_for_restore():
    g, t = make_guide(), new_track()
    adj.set_step_hidden(g, t, "s-bank", True)
    v = view(g, t)
    assert step(v, "s-bank").hidden and step(v, "s-bank").applies == "no"
    assert v.next_step != "s-bank"
    assert {"kind": "step", "id": "s-bank", "title": "打流水"} in v.hidden_items
    adj.set_step_hidden(g, t, "s-bank", False)
    assert view(g, t).next_step == "s-bank"


def test_hidden_requirement_leaves_progress_and_drops_match():
    g = make_guide()
    t = new_track(matches={"r-bank": ["b"]})
    rec = MaterialRecord(id="b", category=MaterialCategory.FINANCIAL_SNAPSHOT, type="银行流水", obtained_date=date(2026, 9, 20))
    before = view(g, t, [rec]).progress_total
    adj.set_requirement_hidden(g, t, "r-bank", True)
    v = view(g, t, [rec])
    assert req(v, "r-bank").state == "not_applicable" and req(v, "r-bank").hidden
    assert v.progress_total == before - 1
    assert "r-bank" not in t.matches


def test_notes_set_and_clear():
    g, t = make_guide(), new_track()
    adj.set_step_note(g, t, "s-bank", "  带上身份证  ")
    adj.set_requirement_note(g, t, "r-bank", "要盖章")
    v = view(g, t)
    assert step(v, "s-bank").user_note == "带上身份证"
    assert req(v, "r-bank").user_note == "要盖章" and req(v, "r-bank").note is None  # note 仍是攻略自带说明
    adj.set_step_note(g, t, "s-bank", "")
    assert view(g, t).steps[0].user_note is None


def test_note_too_long_rejected():
    with pytest.raises(AdjustmentError, match="太长"):
        adj.set_step_note(make_guide(), new_track(), "s-bank", "字" * 501)


def test_unknown_ids_rejected():
    g, t = make_guide(), new_track()
    with pytest.raises(AdjustmentError):
        adj.set_step_hidden(g, t, "s-nope", True)
    with pytest.raises(AdjustmentError):
        adj.set_requirement_note(g, t, "r-nope", "x")
    with pytest.raises(AdjustmentError):
        adj.add_custom_step(g, t, "x", phase="p-nope")


def test_custom_step_placed_after_given_step_and_counts_for_completion():
    g, t = phased(), new_track(facts={"identity": "学生"})
    cs = adj.add_custom_step(g, t, "去银行开存款证明", after="s-bank")
    v = view(g, t)
    ids = [s.id for s in v.steps]
    assert ids[ids.index("s-bank") + 1] == cs.id
    assert step(v, cs.id).custom and step(v, cs.id).phase == "p-prep"
    t.done_steps = ["s-bank", "s-docs", "s-submit"]
    from core.tracks import is_track_complete
    assert not is_track_complete(view(g, t))  # 自己加的步骤没做完，就不算办完
    t.done_steps.append(cs.id)
    assert is_track_complete(view(g, t))


def test_custom_step_without_after_goes_to_end_of_phase():
    g, t = phased(), new_track()
    cs = adj.add_custom_step(g, t, "拍证件照", phase="p-prep")
    ids = [s.id for s in view(g, t).steps]
    assert ids.index(cs.id) == ids.index("s-submit") - 1


def test_custom_material_attached_and_auto_matched_by_name():
    g, t = make_guide(), new_track()
    cm = adj.add_custom_material(g, t, VOCAB, "银行流水", step="s-docs")
    assert cm.material_type == "bank_statement"  # 名字被词表认出
    rec = MaterialRecord(id="b", category=MaterialCategory.FINANCIAL_SNAPSHOT, type="银行流水", obtained_date=date(2026, 9, 20))
    v = view(g, t, [rec])
    assert cm.id in step(v, "s-docs").requirements
    r = req(v, cm.id)
    assert r.custom and r.state == "unconfirmed" and [x.id for x in r.records] == ["b"]


def test_custom_material_unknown_type_is_missing_until_picked():
    g, t = make_guide(), new_track()
    cm = adj.add_custom_material(g, t, VOCAB, "邀请函", step="s-docs", optional=True)
    assert cm.material_type is None
    r = req(view(g, t), cm.id)
    assert r.state == "missing" and r.optional and r.type_unresolved


def test_delete_custom_step_removes_its_materials_and_state():
    g, t = phased(), new_track()
    cs = adj.add_custom_step(g, t, "我的步骤", phase="p-prep")
    later = adj.add_custom_step(g, t, "排在它后面", after=cs.id)
    cm = adj.add_custom_material(g, t, VOCAB, "邀请函", step=cs.id)
    t.done_steps.append(cs.id)
    adj.set_step_note(g, t, cs.id, "备注")
    adj.delete_custom_step(t, cs.id)
    assert t.custom_materials == [] and cs.id not in t.done_steps and cs.id not in t.step_notes
    assert any(s.id == later.id for s in view(g, t).steps)  # 排在它后面的步骤还在
    assert cm.id not in {r.id for r in view(g, t).requirements}


def test_guide_steps_cannot_be_renamed_or_deleted():
    t = new_track()
    with pytest.raises(AdjustmentError, match="攻略原有"):
        adj.delete_custom_step(t, "s-bank")
    with pytest.raises(AdjustmentError, match="攻略原有"):
        adj.update_custom_material(t, "r-bank", name="x")


def test_custom_items_pointing_to_missing_steps_are_skipped():
    from core.tracks import CustomMaterial
    g = make_guide()
    t = new_track(custom_materials=[CustomMaterial(id="cm-1", name="x", step="s-gone")])
    assert "cm-1" not in {r.id for r in view(g, t).requirements}
