"""我的办事（Track）：读写 + 状态计算（specs/002-guide-to-track/spec.md "数据结构 §2" 和 "状态计算"）。

Track 属于个人区，只存在材料根目录下（<materials_root>/tracks/），永远不写进仓库。

`compute_track_view` 是纯函数：给定攻略、Track、材料记录、词表和"今天"，算出界面要展示的
全部状态。不读文件、不看系统时钟，所以测试可以把每种情况都构造出来、结果永远可复现。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from core.guides import Condition, Guide
from core.material_types import Vocabulary
from core.models import MaterialRecord, MaterialStatus
from core.status import compute_status

# 原始资料的时效日期距今超过这么多天，界面提示"可能过时"
SOURCE_STALE_AFTER_DAYS = 365
# materials_index/ 里以此开头的记录是虚构示例（见 README），不参与匹配
EXAMPLE_PREFIX = "example-"

RequirementState = Literal["not_applicable", "undecided", "missing", "stale", "unconfirmed", "ready"]
Applies = Literal["yes", "no", "undecided"]


class TrackNotFoundError(Exception):
    pass


class Track(BaseModel):
    id: str
    guide: str
    title: str
    created: date
    deadline: date | None = None
    facts: dict[str, str] = {}
    done_steps: list[str] = []
    matches: dict[str, list[str]] = {}
    done_checks: list[str] = []
    # 所有适用步骤都做完的那一天；由 sync_completion 自动维护，取消任一步骤会清空。首页据此算"用时"
    completed: date | None = None


# ---------- 读写（个人区） ----------


def tracks_dir(materials_root: Path) -> Path:
    return materials_root / "tracks"


def load_tracks(materials_root: Path) -> list[Track]:
    directory = tracks_dir(materials_root)
    if not directory.is_dir():
        return []
    tracks = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as f:
            tracks.append(Track.model_validate(yaml.safe_load(f)))
    return tracks


def load_track(materials_root: Path, track_id: str) -> Track:
    path = tracks_dir(materials_root) / f"{track_id}.yaml"
    if not path.is_file():
        raise TrackNotFoundError(track_id)
    with path.open("r", encoding="utf-8") as f:
        return Track.model_validate(yaml.safe_load(f))


def save_track(materials_root: Path, track: Track) -> None:
    directory = tracks_dir(materials_root)
    directory.mkdir(parents=True, exist_ok=True)
    data = track.model_dump(mode="json", exclude_none=True)
    with (directory / f"{track.id}.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def create_track(
    materials_root: Path, guide: Guide, today: date, title: str | None = None, deadline: date | None = None
) -> Track:
    """按 <guide-id>-<YYYYMMDD> 生成 id，重名时追加 -2、-3……，不覆盖已有 Track。"""
    base = f"{guide.id}-{today:%Y%m%d}"
    existing = {p.stem for p in tracks_dir(materials_root).glob("*.yaml")} if tracks_dir(materials_root).is_dir() else set()
    track_id, n = base, 2
    while track_id in existing:
        track_id, n = f"{base}-{n}", n + 1
    track = Track(id=track_id, guide=guide.id, title=title or guide.title, created=today, deadline=deadline)
    save_track(materials_root, track)
    return track


# ---------- 状态计算（纯函数） ----------


class CandidateView(BaseModel):
    id: str
    type: str
    sublabel: str | None
    obtained_date: date | None
    status: MaterialStatus


class FactView(BaseModel):
    key: str
    question: str
    options: list[str]
    value: str | None
    asked: bool


class RequirementView(BaseModel):
    id: str
    name: str
    raw_name: str | None
    material_type: str | None
    type_unresolved: bool
    kind: str
    optional: bool
    note: str | None
    freshness_days: int | None
    state: RequirementState
    confirmed: bool
    records: list[CandidateView]  # 已确认的记录；没确认时是候选记录
    # 组合类型缺了哪几部分 [{key, name}]，界面据此说清楚"还差什么"，并按部分上传
    missing_parts: list[dict]
    parts: list[dict]  # 组合类型的全部组成部分 [{key, name}]；非组合类型为空
    conditions: list[dict]  # 原样的 applies_if，界面用来解释"为什么待定/取决于什么"
    evidence: list[dict]


class PhaseView(BaseModel):
    id: str
    title: str
    summary: str | None
    mode: str | None
    estimate: str | None
    duration_days: dict | None
    # done 全部做完 | current 下一步就在这个阶段 | upcoming 还没到 | skipped 没有适用于你的步骤
    state: Literal["done", "current", "upcoming", "skipped"]
    steps_done: int
    steps_total: int
    evidence: list[dict]


class StepView(BaseModel):
    id: str
    title: str
    phase: str | None
    where: str | None
    estimate: str | None
    duration_days: dict | None
    applies: Applies
    done: bool
    available: bool
    requirements: list[str]
    depends_on: list[str]
    conditions: list[dict]
    evidence: list[dict]


class CheckView(BaseModel):
    id: str
    text: str
    involves: list[str]
    done: bool


class TrackView(BaseModel):
    id: str
    title: str
    guide_id: str
    guide_title: str
    created: date
    deadline: date | None
    completed: date | None
    elapsed_days: int  # 从创建到完成（没完成就到今天）经过的天数
    facts: list[FactView]
    requirements: list[RequirementView]
    steps: list[StepView]
    next_step: str | None
    timeline: str | None
    phases: list[PhaseView]
    progress_ready: int
    progress_total: int
    checks: list[CheckView]
    conflicts: list[dict]
    uncertain: list[str]
    sources: list[dict]
    stale_sources: list[str]


def _fact_ask_state(guide: Guide, answers: dict[str, str], key: str, _seen: frozenset = frozenset()) -> Applies:
    """这个问题该不该问：yes 要问；no 不适用（永远不问）；undecided 取决于另一个还没回答的问题，暂时不问。"""
    fact = guide.facts[key]
    if not fact.ask_if:
        return "yes"
    if key in _seen:  # 校验已禁止自引用；这里再防一手间接成环，避免无限递归
        return "no"
    return _evaluate(guide, answers, fact.ask_if, _seen | {key})


def _evaluate(guide: Guide, answers: dict[str, str], conditions: list[Condition], _seen: frozenset = frozenset()) -> Applies:
    """spec "条件判定"：任一不满足 → no；否则任一未定 → undecided；否则 yes。"""
    undecided = False
    for c in conditions:
        if c.fact not in guide.facts:
            return "no"
        ask = _fact_ask_state(guide, answers, c.fact, _seen)
        if ask == "no":
            return "no"
        value = answers.get(c.fact) if ask == "yes" else None
        if value is None:
            undecided = True
        elif value not in c.in_:
            return "no"
    return "undecided" if undecided else "yes"


def _record_type(record: MaterialRecord, vocab: Vocabulary) -> str | None:
    return record.material_type or vocab.lookup(record.type)


def _latest(records: list[MaterialRecord]) -> MaterialRecord | None:
    obtained = [r for r in records if r.obtained_date is not None]
    return max(obtained, key=lambda r: r.obtained_date) if obtained else None


def _candidates(type_key: str, by_type: dict[str, list[MaterialRecord]], vocab: Vocabulary) -> list[MaterialRecord] | None:
    """返回满足该类型所需的记录；凑不齐返回 None。组合类型优先用直接标成该类型的记录，否则每个 part 各取一条。"""
    direct = _latest(by_type.get(type_key, []))
    if direct is not None:
        return [direct]
    parts = vocab.types[type_key].parts if type_key in vocab.types else ()
    if not parts:
        return None
    picked = [_latest(by_type.get(p, [])) for p in parts]
    return None if any(r is None for r in picked) else picked


def _is_stale(record: MaterialRecord, freshness_days: int | None, today: date) -> bool:
    if compute_status(record, today).status == MaterialStatus.EXPIRED:
        return True
    if freshness_days is not None and record.obtained_date is not None:
        return (today - record.obtained_date).days > freshness_days
    return False


def compute_track_view(
    guide: Guide, track: Track, records: list[MaterialRecord], vocab: Vocabulary, today: date
) -> TrackView:
    answers = {k: v for k, v in track.facts.items() if k in guide.facts}
    records_by_id = {r.id: r for r in records}
    by_type: dict[str, list[MaterialRecord]] = {}
    for r in records:
        if r.id.startswith(EXAMPLE_PREFIX):
            continue  # 虚构示例数据只用来演示格式，不能被当成真实材料匹配给一件真实的办事
        key = _record_type(r, vocab)
        if key is not None:
            by_type.setdefault(key, []).append(r)

    facts = [
        FactView(
            key=k, question=f.question, options=f.options, value=answers.get(k),
            asked=_fact_ask_state(guide, answers, k) == "yes",
        )
        for k, f in guide.facts.items()
    ]

    req_views: list[RequirementView] = []
    for q in guide.requirements:
        type_key = q.material_type or vocab.lookup(q.raw_name)
        applies = _evaluate(guide, answers, q.applies_if)
        confirmed_ids = track.matches.get(q.id)
        confirmed = bool(confirmed_ids) and all(i in records_by_id for i in confirmed_ids)

        chosen: list[MaterialRecord] | None
        if confirmed:
            chosen = [records_by_id[i] for i in confirmed_ids]
        elif type_key is not None:
            chosen = _candidates(type_key, by_type, vocab)
        else:
            chosen = None

        state: RequirementState
        if applies == "no":
            state = "not_applicable"
        elif applies == "undecided":
            state = "undecided"
        elif not chosen:
            state = "missing"
        elif any(_is_stale(r, q.freshness_days, today) for r in chosen):
            state = "stale"
        elif not confirmed:
            state = "unconfirmed"
        else:
            state = "ready"

        missing_parts: list[dict] = []
        if state == "missing" and type_key in vocab.types:
            missing_parts = [
                {"key": p, "name": vocab.types[p].name}
                for p in vocab.types[type_key].parts if _latest(by_type.get(p, [])) is None
            ]

        req_views.append(RequirementView(
            id=q.id,
            name=vocab.name_of(type_key) or q.raw_name or q.id,
            raw_name=q.raw_name,
            material_type=type_key,
            type_unresolved=type_key is None,
            kind=q.kind,
            optional=q.optional,
            note=q.note,
            freshness_days=q.freshness_days,
            state=state,
            confirmed=confirmed,
            records=[
                CandidateView(
                    id=r.id, type=r.type, sublabel=r.sublabel, obtained_date=r.obtained_date,
                    status=compute_status(r, today).status,
                )
                for r in (chosen or [])
            ],
            missing_parts=missing_parts,
            parts=[
                {"key": p, "name": vocab.types[p].name}
                for p in (vocab.types[type_key].parts if type_key in vocab.types else ())
            ],
            conditions=[{"fact": c.fact, "in": c.in_} for c in q.applies_if],
            evidence=[e.model_dump() for e in q.evidence],
        ))

    step_applies = {s.id: _evaluate(guide, answers, s.applies_if) for s in guide.steps}
    done = set(track.done_steps)
    step_views: list[StepView] = []
    for s in guide.steps:
        deps_ok = all(d in done or step_applies.get(d) == "no" for d in s.depends_on)
        applies = step_applies[s.id]
        is_done = s.id in done
        step_views.append(StepView(
            id=s.id, title=s.title, phase=s.phase, where=s.where, estimate=s.estimate,
            duration_days=s.duration_days.model_dump() if s.duration_days else None,
            applies=applies, done=is_done,
            available=applies == "yes" and not is_done and deps_ok,
            requirements=s.requirements, depends_on=s.depends_on,
            conditions=[{"fact": c.fact, "in": c.in_} for c in s.applies_if],
            evidence=[e.model_dump() for e in s.evidence],
        ))
    next_step = next((s.id for s in step_views if s.available), None)
    phase_views = _phase_views(guide, step_views, next_step)

    counted = [r for r in req_views if not r.optional and r.state not in ("not_applicable", "undecided")]
    stale_sources = [
        s.id for s in guide.sources
        if s.as_of is not None and (today - s.as_of).days > SOURCE_STALE_AFTER_DAYS
    ]

    return TrackView(
        id=track.id, title=track.title, guide_id=guide.id, guide_title=guide.title,
        created=track.created, deadline=track.deadline, completed=track.completed,
        elapsed_days=((track.completed or today) - track.created).days,
        facts=facts, requirements=req_views, steps=step_views, next_step=next_step,
        timeline=guide.timeline, phases=phase_views,
        progress_ready=sum(r.state == "ready" for r in counted), progress_total=len(counted),
        checks=[CheckView(id=c.id, text=c.text, involves=c.involves, done=c.id in track.done_checks) for c in guide.checks],
        conflicts=[k.model_dump() for k in guide.conflicts],
        uncertain=guide.uncertain,
        sources=[s.model_dump(mode="json") for s in guide.sources],
        stale_sources=stale_sources,
    )


def _phase_views(guide: Guide, steps: list[StepView], next_step: str | None) -> list[PhaseView]:
    """阶段状态：全部适用步骤做完 → done；下一步落在这里 → current；没有适用步骤 → skipped；其余 upcoming。

    没有"下一步"（例如还有问题没回答，或全部做完）时，第一个没做完的阶段算 current，
    保证进度条上总能看出"现在大概走到哪了"。
    """
    by_id = {s.id: s for s in steps}
    current_phase = by_id[next_step].phase if next_step else None
    views: list[PhaseView] = []
    for p in guide.phases:
        mine = [s for s in steps if s.phase == p.id and s.applies != "no"]
        done = sum(s.done for s in mine)
        if not mine:
            state = "skipped"
        elif done == len(mine):
            state = "done"
        elif p.id == current_phase:
            state = "current"
        else:
            state = "upcoming"
        views.append(PhaseView(
            id=p.id, title=p.title, summary=p.summary, mode=p.mode, estimate=p.estimate,
            duration_days=p.duration_days.model_dump() if p.duration_days else None,
            state=state, steps_done=done, steps_total=len(mine),
            evidence=[e.model_dump() for e in p.evidence],
        ))
    if current_phase is None:
        first_open = next((v for v in views if v.state == "upcoming"), None)
        if first_open is not None:
            first_open.state = "current"
    return views


def is_track_complete(view: TrackView) -> bool:
    """全部生效的步骤都做完、且没有"取决于还没回答的问题"的步骤，才算办完。"""
    relevant = [s for s in view.steps if s.applies != "no"]
    return bool(relevant) and all(s.applies == "yes" and s.done for s in relevant)


def sync_completion(track: Track, view: TrackView, today: date) -> None:
    """根据最新状态维护 track.completed：刚办完记下今天；已经记过就保留原日期；又有没做完的就清空。"""
    if is_track_complete(view):
        if track.completed is None:
            track.completed = today
    else:
        track.completed = None
