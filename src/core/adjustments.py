"""个人调整：隐藏 / 备注 / 自己加步骤和材料（specs/002 "我的办事 · 个人调整"）。

这里的函数只修改传进来的 Track 对象（不读写文件），出错时抛 AdjustmentError（中文原因）。
网页 API 和 MCP 工具都调用这一份，保证"界面上做"和"让 Agent 做"行为完全一致。
"""

from __future__ import annotations

from uuid import uuid4

from core.guides import Guide
from core.material_types import Vocabulary
from core.tracks import CustomMaterial, CustomStep, Track, apply_adjustments

MAX_NOTE_CHARS = 500
MAX_TITLE_CHARS = 100


class AdjustmentError(ValueError):
    pass


def _effective(guide: Guide, track: Track) -> Guide:
    return apply_adjustments(guide, track)


def _step_ids(guide: Guide, track: Track) -> set[str]:
    return {s.id for s in _effective(guide, track).steps}


def _requirement_ids(guide: Guide, track: Track) -> set[str]:
    return {r.id for r in _effective(guide, track).requirements}


def _clean(text: str | None, limit: int, what: str) -> str:
    text = (text or "").strip()
    if not text:
        raise AdjustmentError(f"{what}不能为空")
    if len(text) > limit:
        raise AdjustmentError(f"{what}太长了（最多 {limit} 字）")
    return text


def _toggle(items: list[str], item: str, on: bool) -> list[str]:
    rest = [x for x in items if x != item]
    return rest + [item] if on else rest


def set_step_hidden(guide: Guide, track: Track, step_id: str, hidden: bool) -> None:
    if step_id not in _step_ids(guide, track):
        raise AdjustmentError(f"没有这个步骤：{step_id}")
    track.hidden_steps = _toggle(track.hidden_steps, step_id, hidden)


def set_requirement_hidden(guide: Guide, track: Track, requirement_id: str, hidden: bool) -> None:
    if requirement_id not in _requirement_ids(guide, track):
        raise AdjustmentError(f"没有这项材料：{requirement_id}")
    track.hidden_requirements = _toggle(track.hidden_requirements, requirement_id, hidden)
    if hidden:
        track.matches.pop(requirement_id, None)  # 隐藏了就不再占用确认过的材料


def set_step_note(guide: Guide, track: Track, step_id: str, note: str | None) -> None:
    if step_id not in _step_ids(guide, track):
        raise AdjustmentError(f"没有这个步骤：{step_id}")
    if note is None or not note.strip():
        track.step_notes.pop(step_id, None)
    else:
        track.step_notes[step_id] = _clean(note, MAX_NOTE_CHARS, "备注")


def set_requirement_note(guide: Guide, track: Track, requirement_id: str, note: str | None) -> None:
    if requirement_id not in _requirement_ids(guide, track):
        raise AdjustmentError(f"没有这项材料：{requirement_id}")
    if note is None or not note.strip():
        track.requirement_notes.pop(requirement_id, None)
    else:
        track.requirement_notes[requirement_id] = _clean(note, MAX_NOTE_CHARS, "备注")


def add_custom_step(
    guide: Guide, track: Track, title: str, phase: str | None = None, after: str | None = None, where: str | None = None
) -> CustomStep:
    if phase is not None and phase not in {p.id for p in guide.phases}:
        raise AdjustmentError(f"没有这个阶段：{phase}")
    if after is not None and after not in _step_ids(guide, track):
        raise AdjustmentError(f"没有这个步骤：{after}")
    step = CustomStep(
        id=f"cs-{uuid4().hex[:8]}",
        title=_clean(title, MAX_TITLE_CHARS, "步骤名称"),
        phase=phase,
        after=after,
        where=where.strip() if where and where.strip() else None,
    )
    track.custom_steps.append(step)
    return step


def update_custom_step(track: Track, step_id: str, title: str | None = None, where: str | None = None) -> None:
    step = next((s for s in track.custom_steps if s.id == step_id), None)
    if step is None:
        raise AdjustmentError(f"没有这个自己加的步骤：{step_id}（攻略原有的步骤不能改名，可以加备注）")
    if title is not None:
        step.title = _clean(title, MAX_TITLE_CHARS, "步骤名称")
    if where is not None:
        step.where = where.strip() or None


def delete_custom_step(track: Track, step_id: str) -> None:
    """删掉自己加的步骤；挂在它下面的自己加的材料一起删，相关的完成状态、备注、确认也清掉。
    其他自己加的步骤如果排在它后面（after 指向它），改为排在它原来的位置之后，不跟着消失。"""
    step = next((s for s in track.custom_steps if s.id == step_id), None)
    if step is None:
        raise AdjustmentError(f"没有这个自己加的步骤：{step_id}（攻略原有的步骤不能删，可以隐藏）")
    track.custom_steps = [s for s in track.custom_steps if s.id != step_id]
    for other in track.custom_steps:
        if other.after == step_id:
            other.after = step.after
            other.phase = other.phase or step.phase
    for m in [m for m in track.custom_materials if m.step == step_id]:
        _forget_material(track, m.id)
    track.done_steps = [s for s in track.done_steps if s != step_id]
    track.hidden_steps = [s for s in track.hidden_steps if s != step_id]
    track.step_notes.pop(step_id, None)


def add_custom_material(
    guide: Guide,
    track: Track,
    vocab: Vocabulary,
    name: str,
    step: str,
    material_type: str | None = None,
    optional: bool = False,
) -> CustomMaterial:
    if step not in _step_ids(guide, track):
        raise AdjustmentError(f"没有这个步骤：{step}")
    clean_name = _clean(name, MAX_TITLE_CHARS, "材料名称")
    if material_type is not None and material_type not in vocab.types:
        raise AdjustmentError(f"词表里没有这种材料类型：{material_type}")
    material = CustomMaterial(
        id=f"cm-{uuid4().hex[:8]}",
        name=clean_name,
        step=step,
        # 没指定类型时按名字查一下词表，能认出来就能自动匹配材料库
        material_type=material_type or vocab.lookup(clean_name),
        optional=optional,
    )
    track.custom_materials.append(material)
    return material


def update_custom_material(track: Track, material_id: str, name: str | None = None, optional: bool | None = None) -> None:
    material = next((m for m in track.custom_materials if m.id == material_id), None)
    if material is None:
        raise AdjustmentError(f"没有这项自己加的材料：{material_id}（攻略原有的材料不能改名，可以加备注）")
    if name is not None:
        material.name = _clean(name, MAX_TITLE_CHARS, "材料名称")
    if optional is not None:
        material.optional = optional


def delete_custom_material(track: Track, material_id: str) -> None:
    if not any(m.id == material_id for m in track.custom_materials):
        raise AdjustmentError(f"没有这项自己加的材料：{material_id}（攻略原有的材料不能删，可以隐藏）")
    _forget_material(track, material_id)


def _forget_material(track: Track, material_id: str) -> None:
    track.custom_materials = [m for m in track.custom_materials if m.id != material_id]
    track.matches.pop(material_id, None)
    track.hidden_requirements = [r for r in track.hidden_requirements if r != material_id]
    track.requirement_notes.pop(material_id, None)
