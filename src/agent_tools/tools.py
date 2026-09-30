"""给本地 Agent（Claude Code / Codex 等）用的纯函数工具集（spec 002 "Agent 接入方案" B2）。

设计原则：
- 每个函数只做一件事，直接调用 `core.*` 和 `config`，不经过 HTTP，行为与 `src/api/app.py`
  对应的接口保持一致（包括"要不要在写操作后调用 `sync_completion`"这类细节——见各函数注释）。
- 目录（材料根目录 / 共享区 / 材料索引）默认从 `config` 模块动态读取，方便测试用
  `monkeypatch.setattr(config, "get_materials_root", lambda: tmp_path)` 之类的方式注入
  临时目录；也可以通过关键字参数显式传入，两种方式都支持。
- 只暴露"读 + 受控写"，不提供删除、不提供读取材料文件内容本身的工具（见 spec 的硬性要求）。
- 返回值一律是 JSON 可序列化的 dict / list（pydantic 模型用 `model_dump(mode="json")`
  转换，日期会变成 `YYYY-MM-DD` 字符串），方便直接塞进 MCP 的结构化返回。

错误约定：
- Track 不存在：抛 `core.tracks.TrackNotFoundError`。
- 攻略不存在 / 没通过校验、问题 / 步骤 / 需求不存在、传入非法选项：抛 `ValueError`，
  消息是中文，可以直接展示给用户。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import ValidationError

import config
from core.guides import Guide, GuideLoadResult, load_all_guides
from core.material_types import Vocabulary, VocabularyError, load_vocabulary
from core.models import describe_personal_profile
from core.profile_storage import confirm_profile_none, load_personal_profile, profile_gaps, update_profile_fields
from core.storage import load_material_records
import core.adjustments as adj
from core.adjustments import AdjustmentError
from core.tracks import (
    Pitfall,
    Track,
    apply_adjustments,
    TrackNotFoundError,
    TrackView,
    compute_track_view,
    set_fact_value,
    set_step_done as _mark_step_done,
    load_track,
    load_tracks,
    save_track,
    sync_completion,
)

# ---------- 目录解析（默认读 config，测试可以 monkeypatch config 或直接传参覆盖） ----------


def _community_dir(override: Path | None = None) -> Path:
    return override if override is not None else config.COMMUNITY_DIR


def _materials_index_dir(override: Path | None = None) -> Path:
    return override if override is not None else config.get_materials_index_dir()


def _materials_root(override: Path | None = None) -> Path:
    return override if override is not None else config.get_materials_root()


# ---------- 内部小工具（不对外暴露，供下面几个工具函数复用） ----------


def _vocabulary(community_dir: Path) -> Vocabulary:
    try:
        return load_vocabulary(community_dir / "material_types.yaml")
    except VocabularyError as e:
        raise ValueError(f"共享词表有错误：{e}") from e


def _guide_results(community_dir: Path) -> tuple[Vocabulary, list[GuideLoadResult]]:
    vocab = _vocabulary(community_dir)
    return vocab, load_all_guides(community_dir / "guides", vocab)


def _find_valid_guide(guide_id: str, community_dir: Path) -> tuple[Vocabulary, Guide]:
    vocab, results = _guide_results(community_dir)
    for r in results:
        if r.path.stem == guide_id:
            if not r.valid:
                raise ValueError(f"攻略 {guide_id} 没有通过校验：" + "；".join(r.errors))
            return vocab, r.guide
    raise ValueError(f"没有找到攻略：{guide_id}")

def _summarize(result: GuideLoadResult, community_dir: Path) -> dict:
    g = result.guide
    return {
        "id": g.id if g else result.path.stem,
        "file": str(result.path.relative_to(community_dir.parent)),
        "title": g.title if g else None,
        "category": g.category if g else None,
        "summary": g.summary if g else None,
        "updated": g.updated.isoformat() if g and g.updated else None,
        "requirement_count": len(g.requirements) if g else 0,
        "step_count": len(g.steps) if g else 0,
        "valid": result.valid,
        "errors": result.errors,
    }


def _load_track_view(
    track: Track, community_dir: Path, materials_index_dir: Path, today: date
) -> TrackView:
    _, guide = _find_valid_guide(track.guide, community_dir)
    records = load_material_records(materials_index_dir)
    return compute_track_view(guide, track, records, _vocabulary(community_dir), today)


def _save_track_and_view(
    track: Track,
    materials_root: Path,
    community_dir: Path,
    materials_index_dir: Path,
    today: date,
) -> TrackView:
    """对应 `src/api/app.py` 里的 `_save_track`：保存前按最新状态维护"办完日期"。"""
    view = _load_track_view(track, community_dir, materials_index_dir, today)
    before = track.completed
    sync_completion(track, view, today)
    save_track(materials_root, track)
    if track.completed != before:
        return _load_track_view(track, community_dir, materials_index_dir, today)
    return view


def _load_track_or_raise(track_id: str, materials_root: Path) -> Track:
    return load_track(materials_root, track_id)  # 找不到时 core 自己抛 TrackNotFoundError


# ---------- 对外暴露的工具函数 ----------


def list_guides(*, community_dir: Path | None = None) -> list[dict]:
    """列出共享区里全部流程攻略（含无效的，标 valid=False 和 errors）。"""
    community_dir = _community_dir(community_dir)
    _, results = _guide_results(community_dir)
    return [_summarize(r, community_dir) for r in results]


def get_guide(
    guide_id: str,
    *,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
    today: date | None = None,
) -> dict:
    """一份攻略的详情 + 预览视图（用一个空白、未保存的 Track 算出——还没开始办，就能看到已有哪些材料）。"""
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()
    _, results = _guide_results(community_dir)
    for r in results:
        if r.path.stem == guide_id:
            preview = None
            if r.valid:
                blank = Track(id="preview", guide=r.guide.id, title=r.guide.title, created=today)
                preview = _load_track_view(blank, community_dir, materials_index_dir, today).model_dump(
                    mode="json"
                )
            return {"summary": _summarize(r, community_dir), "preview": preview}
    raise ValueError(f"没有找到攻略：{guide_id}")


def list_tracks(
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
    today: date | None = None,
) -> list[dict]:
    """列出我的全部办事（个人区），附带简要进度；攻略被删了/改坏了也照样列出，只标错误原因。"""
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()

    summaries: list[dict] = []
    for track in load_tracks(materials_root):
        base = {
            "id": track.id,
            "title": track.title,
            "guide_id": track.guide,
            "created": track.created.isoformat(),
            "deadline": track.deadline.isoformat() if track.deadline else None,
            "completed": track.completed.isoformat() if track.completed else None,
        }
        try:
            view = _load_track_view(track, community_dir, materials_index_dir, today)
            _, guide = _find_valid_guide(track.guide, community_dir)
        except ValueError as e:
            summaries.append({
                **base, "category": None, "elapsed_days": None,
                "progress_ready": None, "progress_total": None,
                "next_step_title": None, "error": str(e),
            })
            continue
        next_title = next((s.title for s in view.steps if s.id == view.next_step), None)
        summaries.append({
            **base, "category": guide.category, "elapsed_days": view.elapsed_days,
            "progress_ready": view.progress_ready, "progress_total": view.progress_total,
            "next_step_title": next_title, "error": None,
        })
    return summaries


def read_track_material(
    track_id: str,
    record_id: str,
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
) -> dict:
    """「让 Agent 整理行程」读一份这件事的材料（spec 007 第 2 步）。

    只有 trip_extract 任务能用（环境变量 PA_AGENT_KIND）；record_id 必须是这件事的材料（TrackView.trip_materials）。
    返回 {"type", "text"} 或 {"type", "images": [(bytes, 格式)]}；读不了抛 ValueError。
    """
    import os

    from agent_tools.activity import KIND_ENV
    from core.material_text import MaterialReadError, read_material
    from core.trip import FOLDER_PREFIX

    if os.environ.get(KIND_ENV) != "trip_extract":
        raise ValueError("read_track_material 只在「让 Agent 整理行程」的任务里用")
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    track = _load_track_or_raise(track_id, materials_root)
    view = _load_track_view(track, community_dir, materials_index_dir, date.today())
    if record_id not in {m["id"] for m in view.trip_materials}:
        raise ValueError(f"{record_id} 不是这件办事的材料，不能读")
    if record_id.startswith(FOLDER_PREFIX):  # 这件事的文件夹里的文件（spec 007 第 4 步），read_material 会检查落在文件夹里面
        rel = record_id[len(FOLDER_PREFIX):]
        try:
            return {"type": rel, **read_material(Path(track.folder), rel)}
        except MaterialReadError as e:
            raise ValueError(str(e)) from e
    record = next(r for r in load_material_records(materials_index_dir) if r.id == record_id)
    try:
        return {"type": record.type, **read_material(materials_root, record.file_ref)}
    except MaterialReadError as e:
        raise ValueError(str(e)) from e


def get_track(
    track_id: str,
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
    today: date | None = None,
) -> dict:
    """一件办事的完整状态（`TrackView` 的 JSON）。Track 不存在时抛 `TrackNotFoundError`。"""
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()
    track = _load_track_or_raise(track_id, materials_root)
    return _load_track_view(track, community_dir, materials_index_dir, today).model_dump(mode="json")


def set_fact(
    track_id: str,
    fact: str,
    value: str | None,
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
    today: date | None = None,
) -> dict:
    """回答攻略里的一个问题；`value=None` 清除这个回答。对应 `PUT /api/tracks/{id}/facts/{fact}`。"""
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()

    track = _load_track_or_raise(track_id, materials_root)
    _, guide = _find_valid_guide(track.guide, community_dir)
    set_fact_value(guide, track, fact, value)
    view = _save_track_and_view(track, materials_root, community_dir, materials_index_dir, today)
    return view.model_dump(mode="json")


def set_step_done(
    track_id: str,
    step_id: str,
    done: bool,
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
    today: date | None = None,
) -> dict:
    """勾选/取消一个步骤。对应 `PUT /api/tracks/{id}/steps/{step}`；写完会同步"办完日期"。"""
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()

    track = _load_track_or_raise(track_id, materials_root)
    _, guide = _find_valid_guide(track.guide, community_dir)
    if not any(s.id == step_id for s in apply_adjustments(guide, track).steps):
        raise ValueError(f"这件办事里没有步骤 {step_id}")
    _mark_step_done(track, step_id, done, today)
    view = _save_track_and_view(track, materials_root, community_dir, materials_index_dir, today)
    return view.model_dump(mode="json")


def confirm_match(
    track_id: str,
    requirement_id: str,
    confirmed: bool,
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
    materials_index_dir: Path | None = None,
    today: date | None = None,
) -> dict:
    """确认/取消确认一条需求对应的材料记录。对应 `PUT /api/tracks/{id}/matches/{requirement}`。

    注意：`src/api/app.py` 的这个接口不调用 `sync_completion`（只有勾步骤会改变"是否办完"），
    这里保持和 API 完全一致的行为，不额外调用。
    """
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()

    track = _load_track_or_raise(track_id, materials_root)
    if not confirmed:
        track.matches.pop(requirement_id, None)
    else:
        view = _load_track_view(track, community_dir, materials_index_dir, today)
        req = next((r for r in view.requirements if r.id == requirement_id), None)
        if req is None:
            raise ValueError(f"这份攻略没有需求 {requirement_id}")
        if not req.records:
            raise ValueError("材料库里还没有能满足这条需求的记录")
        track.matches[requirement_id] = [r.id for r in req.records]
    save_track(materials_root, track)
    return _load_track_view(track, community_dir, materials_index_dir, today).model_dump(mode="json")


def validate_community(*, community_dir: Path | None = None) -> dict:
    """校验共享区（词表 + 全部攻略），返回结构与 `PYTHONPATH=src uv run python -m core.guides` 一致的信息。"""
    community_dir = _community_dir(community_dir)
    try:
        vocab = load_vocabulary(community_dir / "material_types.yaml")
    except VocabularyError as e:
        return {"vocabulary": {"valid": False, "error": str(e), "type_count": 0}, "guides": []}

    guides: list[dict] = []
    for r in load_all_guides(community_dir / "guides", vocab):
        rel = str(r.path.relative_to(community_dir.parent))
        if r.valid:
            g = r.guide
            unresolved = [
                q.id for q in g.requirements
                if (q.material_type or vocab.lookup(q.raw_name)) is None
            ]
            guides.append({
                "id": g.id, "file": rel, "valid": True, "errors": [],
                "requirement_count": len(g.requirements), "step_count": len(g.steps),
                "unresolved_types": unresolved,
            })
        else:
            guides.append({
                "id": r.path.stem, "file": rel, "valid": False, "errors": r.errors,
                "requirement_count": 0, "step_count": 0, "unresolved_types": [],
            })
    return {
        "vocabulary": {"valid": True, "error": None, "type_count": len(vocab.types)},
        "guides": guides,
    }


# ---------- 个人调整（与网页 API 共用 core/adjustments.py；不提供删除） ----------


def _adjust(track_id: str, action, materials_root, community_dir, materials_index_dir, today) -> dict:
    materials_root = _materials_root(materials_root)
    community_dir = _community_dir(community_dir)
    materials_index_dir = _materials_index_dir(materials_index_dir)
    today = today or date.today()
    track = _load_track_or_raise(track_id, materials_root)
    vocab, guide = _find_valid_guide(track.guide, community_dir)
    try:
        action(guide, track, vocab)
    except AdjustmentError as e:
        raise ValueError(str(e)) from e
    return _save_track_and_view(track, materials_root, community_dir, materials_index_dir, today).model_dump(mode="json")


def set_hidden(
    track_id: str, kind: str, item_id: str, hidden: bool, *,
    materials_root: Path | None = None, community_dir: Path | None = None,
    materials_index_dir: Path | None = None, today: date | None = None,
) -> dict:
    """隐藏/恢复一个步骤（kind="step"）或一项材料（kind="requirement"）。"""
    if kind == "step":
        fn = lambda g, t, v: adj.set_step_hidden(g, t, item_id, hidden)  # noqa: E731
    elif kind == "requirement":
        fn = lambda g, t, v: adj.set_requirement_hidden(g, t, item_id, hidden)  # noqa: E731
    else:
        raise ValueError('kind 只能是 "step" 或 "requirement"')
    return _adjust(track_id, fn, materials_root, community_dir, materials_index_dir, today)


def set_note(
    track_id: str, kind: str, item_id: str, note: str | None, *,
    materials_root: Path | None = None, community_dir: Path | None = None,
    materials_index_dir: Path | None = None, today: date | None = None,
) -> dict:
    """给步骤（kind="step"）或材料（kind="requirement"）写个人备注；note 为空表示删除备注。"""
    if kind == "step":
        fn = lambda g, t, v: adj.set_step_note(g, t, item_id, note)  # noqa: E731
    elif kind == "requirement":
        fn = lambda g, t, v: adj.set_requirement_note(g, t, item_id, note)  # noqa: E731
    else:
        raise ValueError('kind 只能是 "step" 或 "requirement"')
    return _adjust(track_id, fn, materials_root, community_dir, materials_index_dir, today)


def add_custom_step(
    track_id: str, title: str, phase: str | None = None, after: str | None = None, where: str | None = None, *,
    materials_root: Path | None = None, community_dir: Path | None = None,
    materials_index_dir: Path | None = None, today: date | None = None,
) -> dict:
    """在这件办事里加一个自己的步骤（只存在个人区，不改共享攻略）。"""
    return _adjust(
        track_id, lambda g, t, v: adj.add_custom_step(g, t, title, phase, after, where),
        materials_root, community_dir, materials_index_dir, today,
    )


def add_custom_material(
    track_id: str, name: str, step: str, material_type: str | None = None, optional: bool = False, *,
    materials_root: Path | None = None, community_dir: Path | None = None,
    materials_index_dir: Path | None = None, today: date | None = None,
) -> dict:
    """在某个步骤下加一项自己的材料；名字能被词表认出时会自动匹配材料库。"""
    return _adjust(
        track_id, lambda g, t, v: adj.add_custom_material(g, t, v, name, step, material_type, optional),
        materials_root, community_dir, materials_index_dir, today,
    )


def add_pitfall(
    track_id: str, text: str, *,
    materials_root: Path | None = None, community_dir: Path | None = None,
    materials_index_dir: Path | None = None, today: date | None = None,
) -> dict:
    """记一条避坑点到这件办事右侧的核对清单（1–300 字）。"""
    from uuid import uuid4

    clean = (text or "").strip()
    if not clean or len(clean) > 300:
        raise ValueError("避坑点要 1–300 字")

    def fn(g, t, v):
        t.pitfalls.append(Pitfall(id=f"p-{uuid4().hex[:8]}", text=clean))

    return _adjust(track_id, fn, materials_root, community_dir, materials_index_dir, today)


# ---------- 基本信息（PersonalProfile，specs/003-personal-profile）：读 + 受控写 ----------


def get_personal_profile(*, materials_root: Path | None = None) -> dict:
    """读取「基本信息」整份内容 + 字段说明，给将来的填表 Agent（DS-160 等）用。

    返回 {"profile": ..., "fields": ...}：
    - profile：PersonalProfile 的 JSON（日期是 YYYY-MM-DD；没填的是 null / 空列表）
    - fields：describe_personal_profile() 的输出，每个字段带中文标签、类型、sensitive、ds160 提示
    写回用户的回答用 update_personal_profile（只写用户亲口回答并确认过的内容）。
    文件格式有误时抛 core.profile_storage.ProfileFileError（ValueError 的子类，消息是中文）。
    """
    profile = load_personal_profile(_materials_root(materials_root))
    return {"profile": profile.model_dump(mode="json"), "fields": describe_personal_profile()}


def update_personal_profile(group: str, changes: dict, *, materials_root: Path | None = None) -> dict:
    """把用户在填表过程中回答的长期信息写回「基本信息」的一个分组。

    changes 只放要改的字段（{"字段 key": 值}）；对象字段（例如 father）逐键合并，
    列表字段（例如 schools）整体替换。返回 {"group", "changed": [{field, before, after}]}，
    不返回整份资料。分组不存在、字段名拼错、值不合法抛 ValueError（中文消息），文件不变。
    """
    try:
        _, changed = update_profile_fields(_materials_root(materials_root), group, changes)
    except KeyError:
        raise ValueError(f"没有这个分组：{group}（可选：identity / passport / contact / family / education / employment / travel / social_media / background）")
    except ValidationError as e:
        raise ValueError(f"基本信息「{group}」写入失败，文件未改动：{e}") from e
    return {"group": group, "changed": changed}


def confirm_personal_profile_none(fields: list[str], *, materials_root: Path | None = None) -> dict:
    """把用户亲口确认"没有"的字段记进「基本信息」的 confirmed_none（例如 ["identity.other_names"]）。

    只收列表字段和可空的文本/对象字段；是非题请用 update_personal_profile 直接写 false。
    字段已经有值、路径不存在时抛 ValueError（中文消息），文件不变。返回 {"added": [...], "confirmed_none": [...]}。
    """
    profile, added = confirm_profile_none(_materials_root(materials_root), fields)
    return {"added": added, "confirmed_none": profile.confirmed_none}


def get_profile_gaps(*, materials_root: Path | None = None) -> dict:
    """填表前查缺口：按 DS-160 页面列出基本信息里每个字段是 filled / confirmed_none / missing。

    不返回字段的值（只返回状态），可以放心整段展示给用户。missing 的要在开始填表前一次问完。
    """
    return profile_gaps(load_personal_profile(_materials_root(materials_root)))


# ---------- 通用填表引擎（spec 005）：扫描脚本 + 填写计划，只读 ----------


def get_form_scan_script() -> dict:
    """返回在官网页面里运行的扫描脚本（不读格子里的值，只列出格子）。"""
    from form_engine.match import scan_script
    return {"script": scan_script()}


def plan_form_fill(scan, allow_sensitive: list[str] | None = None, *,
                   materials_root: Path | None = None, profile=None, track_id: str | None = None) -> dict:
    """扫描结果 + 「基本信息」→ 填写计划。报告不含值；值只在 script 里（交给页面运行）。

    scan：扫描脚本的压缩结果（window.__paScanText 分段读回、原样拼起来的字符串）。
    敏感字段默认不填，列在 sensitive 里；用户同意后把路径放进 allow_sensitive 重新调用。
    拼接出错时抛 ValueError（ScanError）。
    """
    from form_engine.match import default_dictionary, expand_scan, plan
    from form_engine.sites import site_date_format
    fields = expand_scan(scan)
    if profile is None:
        profile = load_personal_profile(_materials_root(materials_root))
    trip = load_track(_materials_root(materials_root), track_id).trip if track_id else None
    result = plan(fields, profile, default_dictionary(), allow_sensitive, site_date_format(fields), trip=trip)
    result.pop("ops")  # Agent 只需要 script（ops 是给插件用的同一份计划，spec 006）
    return result


# ---------- 攻略草稿（spec 004：界面里"新建攻略"的 Agent 只能写草稿，不能直接写 community/） ----------


def _form_ids(community_dir: Path) -> set[str] | None:
    forms = community_dir / "forms"
    return {p.stem for p in forms.glob("*.yaml")} if forms.is_dir() else None


def _draft_call(fn, *args, **kwargs):
    from core.drafts import DraftError

    try:
        return fn(*args, **kwargs)
    except DraftError as e:
        raise ValueError(str(e)) from e


def save_guide_draft(
    guide_id: str,
    yaml_text: str,
    alias_suggestions: list[dict] | None = None,
    guide_type: str = "process",
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
) -> dict:
    """写入 / 覆盖一份攻略草稿并返回校验结果（valid、errors、unresolved 等）。"""
    from core.drafts import save_draft

    cdir = _community_dir(community_dir)
    return _draft_call(save_draft, _materials_root(materials_root), guide_type, guide_id, yaml_text,
                       _vocabulary(cdir), alias_suggestions, _form_ids(cdir))


def get_guide_draft(
    guide_id: str,
    guide_type: str = "process",
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
) -> dict:
    """读一份草稿的全文和校验结果（修改草稿前先读）。"""
    from core.drafts import check_draft, read_draft_text

    root, cdir = _materials_root(materials_root), _community_dir(community_dir)
    text = _draft_call(read_draft_text, root, guide_type, guide_id)
    return {"yaml_text": text, "check": _draft_call(check_draft, root, guide_type, guide_id,
                                                    _vocabulary(cdir), _form_ids(cdir))}


def validate_guide_draft(
    guide_id: str,
    guide_type: str = "process",
    *,
    materials_root: Path | None = None,
    community_dir: Path | None = None,
) -> dict:
    from core.drafts import check_draft

    cdir = _community_dir(community_dir)
    return _draft_call(check_draft, _materials_root(materials_root), guide_type, guide_id,
                       _vocabulary(cdir), _form_ids(cdir))
