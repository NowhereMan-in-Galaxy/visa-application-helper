"""我的办事（Track）：读写 + 状态计算（specs/002-guide-to-track/spec.md "数据结构 §2" 和 "状态计算"）。

Track 属于个人区，只存在材料根目录下（<materials_root>/tracks/），永远不写进仓库。

`compute_track_view` 是纯函数：给定攻略、Track、材料记录、词表和"今天"，算出界面要展示的
全部状态。不读文件、不看系统时钟，所以测试可以把每种情况都构造出来、结果永远可复现。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from core.guides import DEFAULT_EXPORT_PATTERN, Condition, Guide, Requirement, Step
from core.material_types import Vocabulary
from core.models import MaterialRecord, MaterialStatus
from core.status import compute_status
from core.windows import reminders as _reminders, window_view

# 原始资料的时效日期距今超过这么多天，界面提示"可能过时"
SOURCE_STALE_AFTER_DAYS = 365
# materials_index/ 里以此开头的记录是虚构示例（见 README），不参与匹配
EXAMPLE_PREFIX = "example-"

RequirementState = Literal["not_applicable", "undecided", "missing", "stale", "unconfirmed", "ready"]
Applies = Literal["yes", "no", "undecided"]


class TrackNotFoundError(Exception):
    pass


class Pitfall(BaseModel):
    """用户自己从攻略、帖子里记下的避坑点，显示在办事页右侧的核对清单里。只属于这一件办事（个人区）。"""

    id: str
    text: str
    done: bool = False


class CustomStep(BaseModel):
    """用户自己加的步骤（个人调整）。插在 after 指定的步骤后面；没写 after 就放在所属阶段的末尾。"""

    id: str  # cs-xxxxxxxx
    title: str
    phase: str | None = None
    after: str | None = None
    where: str | None = None


class CustomMaterial(BaseModel):
    """用户自己加的材料（个人调整），挂在某个步骤（攻略原有的或自己加的）下面。"""

    id: str  # cm-xxxxxxxx
    name: str
    step: str
    material_type: str | None = None  # 填了词表类型就能自动匹配材料库；不填就靠手动挑选
    optional: bool = False


class Track(BaseModel):
    id: str
    guide: str
    title: str
    created: date
    deadline: date | None = None
    facts: dict[str, str] = {}
    done_steps: list[str] = []
    # 每个步骤勾完的日期（spec §3c）：时间窗可以从"上一步勾完那天"往后数，例如第 2 年领礼包
    done_on: dict[str, date] = {}
    matches: dict[str, list[str]] = {}
    done_checks: list[str] = []
    # 所有适用步骤都做完的那一天；由 sync_completion 自动维护，取消任一步骤会清空。首页据此算"用时"
    completed: date | None = None
    # 上次导出材料时选的文件夹（例如 ~/Desktop），下次导出默认用它；None 表示用材料根目录下的 exports/
    export_dir: str | None = None
    pitfalls: list[Pitfall] = []
    # ---- 个人调整（只存在个人区，不改共享攻略）----
    hidden_steps: list[str] = []  # 隐藏的步骤：不再算"下一步"、不计进度和倒排时间，可以随时恢复
    hidden_requirements: list[str] = []  # 隐藏的材料：不计进度、不导出，可以随时恢复
    step_notes: dict[str, str] = {}  # 给步骤加的备注（攻略原有步骤或自己加的都可以）
    requirement_notes: dict[str, str] = {}  # 给材料加的备注
    custom_steps: list[CustomStep] = []
    custom_materials: list[CustomMaterial] = []


def apply_adjustments(guide: Guide, track: Track) -> Guide:
    """把用户自己加的步骤和材料叠加到攻略上，得到"这件办事实际要做的流程"。

    叠加后的攻略只在内存里用，不写回共享区；后面的匹配、上传、倒排时间、进度统计全部照常工作，
    不需要为"自定义项"另写一套逻辑。引用了已不存在的步骤的自定义项会被跳过（攻略被修订后也不报错）。
    """
    if not track.custom_steps and not track.custom_materials:
        return guide
    steps = [s.model_copy(deep=True) for s in guide.steps]
    phase_ids = {p.id for p in guide.phases}
    for cs in track.custom_steps:
        phase = cs.phase if cs.phase in phase_ids else None
        step = Step(id=cs.id, title=cs.title, phase=phase, where=cs.where)
        ids = [x.id for x in steps]
        if cs.after in ids:
            pos = ids.index(cs.after) + 1
            if step.phase is None:
                step.phase = steps[pos - 1].phase
        elif phase is not None and any(x.phase == phase for x in steps):
            pos = max(i for i, x in enumerate(steps) if x.phase == phase) + 1
        else:
            pos = len(steps)
            if step.phase is None and guide.phases:
                step.phase = guide.phases[-1].id
        steps.insert(pos, step)
    by_id = {x.id: x for x in steps}
    requirements = list(guide.requirements)
    for cm in track.custom_materials:
        if cm.step not in by_id:
            continue
        requirements.append(Requirement(
            id=cm.id, kind="obtain", material_type=cm.material_type, raw_name=cm.name, optional=cm.optional,
        ))
        by_id[cm.step].requirements.append(cm.id)
    return guide.model_copy(update={"steps": steps, "requirements": requirements})


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
    type: Literal["choice", "date"] = "choice"
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
    export_name: str | None  # 攻略里指定的导出文件名（不含序号模板以外的部分）
    # 在这里上传时，默认要不要放进长期资料库（词表认识且不是一次性类型 → True）
    default_keep: bool = False
    conditions: list[dict]  # 原样的 applies_if，界面用来解释"为什么待定/取决于什么"
    evidence: list[dict]
    custom: bool = False  # 用户自己加的材料
    hidden: bool = False
    user_note: str | None = None  # 用户自己加的备注（note 是攻略里写的说明）


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
    # 阶段内未完成步骤最晚该完成的日期（倒排时间，见"状态计算"）；没有 deadline 或阶段内没有待办步骤时为 null
    latest_finish: date | None = None


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
    # 挂在这一步上的链接（官网 / 填表指南 / 参考），已按回答过滤：条件不满足的不出现，
    # 取决于还没回答的问题的带 applies="undecided"
    links: list[dict] = []
    evidence: list[dict]
    # 倒排时间（见"状态计算"）：只在设了 deadline、且这一步 applies=="yes" 且未完成时才有值
    latest_start: date | None = None
    # today > latest_start；没有 latest_start 时恒为 False
    late: bool = False
    custom: bool = False  # 用户自己加的步骤
    hidden: bool = False
    user_note: str | None = None
    # 可办时间窗（spec §3c）：{opens, closes, state, days, waiting_for}；攻略没给这一步写 window 时为 null
    window: dict | None = None


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
    export_pattern: str
    export_dir: str | None
    pitfalls: list[Pitfall]
    # 被隐藏的步骤和材料 [{kind: "step"|"requirement", id, title}]，界面上用来"恢复"
    hidden_items: list[dict] = []
    # 以后"开始可以办"或"截止"的日子 [{date, kind: opens|closes, step, title}]，按日期排序（spec §3c）
    reminders: list[dict] = []
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


def _link_views(guide: Guide, answers: dict[str, str], step) -> list[dict]:
    views = []
    for link in step.links:
        applies = _evaluate(guide, answers, link.applies_if)
        if applies == "no":
            continue
        views.append({
            "title": link.title, "kind": link.kind, "url": link.url, "form": link.form,
            "applies": applies, "conditions": [{"fact": c.fact, "in": c.in_} for c in link.applies_if],
            "verified": link.verified.isoformat() if link.verified else None,
        })
    return views


def _default_keep(type_key: str | None, vocab: Vocabulary) -> bool:
    """上传时默认要不要放进长期资料库：词表认识、且不是一次性类型（组合类型看各部分）。"""
    if type_key is None or type_key not in vocab.types:
        return False
    t = vocab.types[type_key]
    if t.parts:
        return all(vocab.types[p].reusable for p in t.parts)
    return t.reusable


def record_type(record: MaterialRecord, vocab: Vocabulary) -> str | None:
    """一条材料记录属于词表里的哪个类型：优先用记录上写明的 material_type，否则按 type 走词表推断。"""
    return _record_type(record, vocab)


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
    guide = apply_adjustments(guide, track)
    custom_ids = {c.id for c in track.custom_steps} | {c.id for c in track.custom_materials}
    hidden_steps, hidden_reqs = set(track.hidden_steps), set(track.hidden_requirements)
    answers = {k: v for k, v in track.facts.items() if k in guide.facts}
    records_by_id = {r.id: r for r in records}
    by_type: dict[str, list[MaterialRecord]] = {}
    for r in records:
        if r.id.startswith(EXAMPLE_PREFIX):
            continue  # 虚构示例数据只用来演示格式，不能被当成真实材料匹配给一件真实的办事
        if r.for_track is not None and r.for_track != track.id:
            continue  # 别的办事的"本次专用"材料（例如去年的邀请函），不能匹配给这件办事
        key = _record_type(r, vocab)
        if key is not None:
            by_type.setdefault(key, []).append(r)

    facts = [
        FactView(
            key=k, question=f.question, type=f.type, options=f.options, value=answers.get(k),
            asked=_fact_ask_state(guide, answers, k) == "yes",
        )
        for k, f in guide.facts.items()
    ]

    req_views: list[RequirementView] = []
    for q in guide.requirements:
        type_key = q.material_type or vocab.lookup(q.raw_name)
        # 隐藏的材料按"不适用"处理：不计进度、不导出
        applies = "no" if q.id in hidden_reqs else _evaluate(guide, answers, q.applies_if)
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
            custom=q.id in custom_ids, hidden=q.id in hidden_reqs, user_note=track.requirement_notes.get(q.id),
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
            export_name=q.export_name,
            default_keep=_default_keep(type_key, vocab),
            parts=[
                {"key": p, "name": vocab.types[p].name}
                for p in (vocab.types[type_key].parts if type_key in vocab.types else ())
            ],
            conditions=[{"fact": c.fact, "in": c.in_} for c in q.applies_if],
            evidence=[e.model_dump() for e in q.evidence],
        ))

    # 隐藏的步骤按"不适用"处理：不是下一步、不计完成、不参与倒排时间
    step_applies = {
        s.id: "no" if s.id in hidden_steps else _evaluate(guide, answers, s.applies_if) for s in guide.steps
    }
    done = set(track.done_steps)
    latest_start, latest_finish, late = _deadline_times(guide, step_applies, done, track.deadline, today)
    step_views: list[StepView] = []
    for s in guide.steps:
        deps_ok = all(d in done or step_applies.get(d) == "no" for d in s.depends_on)
        applies = step_applies[s.id]
        is_done = s.id in done
        window = None if applies == "no" or is_done else window_view(s, answers, track.done_on, today)
        in_window = window is None or window["state"] not in ("upcoming", "missed")
        step_views.append(StepView(
            custom=s.id in custom_ids, hidden=s.id in hidden_steps, user_note=track.step_notes.get(s.id),
            id=s.id, title=s.title, phase=s.phase, where=s.where, estimate=s.estimate,
            duration_days=s.duration_days.model_dump() if s.duration_days else None,
            applies=applies, done=is_done,
            available=applies == "yes" and not is_done and deps_ok and in_window,
            requirements=s.requirements, depends_on=s.depends_on,
            conditions=[{"fact": c.fact, "in": c.in_} for c in s.applies_if],
            links=_link_views(guide, answers, s),
            evidence=[e.model_dump() for e in s.evidence],
            latest_start=latest_start.get(s.id), late=late.get(s.id, False),
            window=window,
        ))
    next_step = next((s.id for s in step_views if s.available), None)
    phase_views = _phase_views(guide, step_views, next_step, latest_finish)

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
        export_pattern=guide.export_pattern or DEFAULT_EXPORT_PATTERN,
        export_dir=track.export_dir,
        pitfalls=track.pitfalls,
        hidden_items=[
            {"kind": "step", "id": s.id, "title": s.title} for s in guide.steps if s.id in hidden_steps
        ] + [
            {"kind": "requirement", "id": q.id, "title": vocab.name_of(q.material_type or vocab.lookup(q.raw_name)) or q.raw_name or q.id}
            for q in guide.requirements if q.id in hidden_reqs
        ],
        reminders=_reminders(guide, step_views, today),
        sources=[s.model_dump(mode="json") for s in guide.sources],
        stale_sources=stale_sources,
    )


def set_fact_value(guide: Guide, track: Track, fact: str, value: str | None) -> None:
    """回答（或清除）一个问题，网页接口和 MCP 工具共用。不合法时抛 ValueError（中文原因）。"""
    if fact not in guide.facts:
        raise ValueError(f"这份攻略没有问题 {fact}")
    if value is None:
        track.facts.pop(fact, None)
        return
    f = guide.facts[fact]
    if f.type == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{value!r} 不是 YYYY-MM-DD 格式的日期") from None
        if len(value) != 10:
            raise ValueError(f"{value!r} 不是 YYYY-MM-DD 格式的日期")
    elif value not in f.options:
        raise ValueError(f"{value!r} 不是这个问题的选项")
    track.facts[fact] = value


def set_step_done(track: Track, step: str, done: bool, today: date) -> None:
    """勾选 / 取消一个步骤，并同步勾完的日期（spec §3c）。调用方负责先确认步骤存在。"""
    remaining = [s for s in track.done_steps if s != step]
    track.done_steps = remaining + [step] if done else remaining
    if done:
        track.done_on.setdefault(step, today)
    else:
        track.done_on.pop(step, None)


def _deadline_times(
    guide: Guide, step_applies: dict[str, Applies], done: set[str], deadline: date | None, today: date
) -> tuple[dict[str, date], dict[str, date], dict[str, bool]]:
    """倒排时间（spec "状态计算"）：deadline 为 null 时三个字典都是空的（界面据此得到全 null / 全 False）。

    只对集合 S（生效且未完成的步骤）计算：latest_finish(s) 是"S 中直接依赖 s 的步骤"的 latest_start
    的最小值，没有这样的步骤时用 deadline；latest_start(s) = latest_finish(s) 减去这一步的时长
    （duration_days.max，没有则为 0）。用递归 + 记忆化按依赖图从后往前算，攻略校验已保证无环。
    """
    if deadline is None:
        return {}, {}, {}

    s_ids = {s.id for s in guide.steps if step_applies.get(s.id) == "yes" and s.id not in done}
    steps_by_id = {s.id: s for s in guide.steps}
    # 谁直接依赖谁：只统计依赖方也在 S 里的情况
    dependents: dict[str, list[str]] = {sid: [] for sid in s_ids}
    for s in guide.steps:
        if s.id not in s_ids:
            continue
        for dep in s.depends_on:
            if dep in dependents:
                dependents[dep].append(s.id)

    def dur(step_id: str) -> int:
        d = steps_by_id[step_id].duration_days
        return d.max if d else 0

    latest_start: dict[str, date] = {}
    latest_finish: dict[str, date] = {}

    def compute(sid: str) -> date:
        if sid in latest_start:
            return latest_start[sid]
        deps = dependents.get(sid, [])
        finish = min((compute(d) for d in deps), default=deadline)
        latest_finish[sid] = finish
        start = finish - timedelta(days=dur(sid))
        latest_start[sid] = start
        return start

    for sid in s_ids:
        compute(sid)

    late = {sid: today > latest_start[sid] for sid in s_ids}
    return latest_start, latest_finish, late


def _phase_views(
    guide: Guide, steps: list[StepView], next_step: str | None, latest_finish: dict[str, date] | None = None
) -> list[PhaseView]:
    """阶段状态：全部适用步骤做完 → done；下一步落在这里 → current；没有适用步骤 → skipped；其余 upcoming。

    没有"下一步"（例如还有问题没回答，或全部做完）时，第一个没做完的阶段算 current，
    保证进度条上总能看出"现在大概走到哪了"。
    """
    latest_finish = latest_finish or {}
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
        # 阶段的 latest_finish：这一阶段内属于集合 S（applies=="yes" 且未完成）的步骤里 latest_finish 的最大值
        phase_finishes = [latest_finish[s.id] for s in mine if s.id in latest_finish]
        views.append(PhaseView(
            id=p.id, title=p.title, summary=p.summary, mode=p.mode, estimate=p.estimate,
            duration_days=p.duration_days.model_dump() if p.duration_days else None,
            state=state, steps_done=done, steps_total=len(mine),
            evidence=[e.model_dump() for e in p.evidence],
            latest_finish=max(phase_finishes) if phase_finishes else None,
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
