"""给浏览器插件用的接口（specs/006-browser-extension）。

插件 ID 由 extension/manifest.json 里的固定公钥决定；本地服务只放行这个 ID，而且只放行 /api/ext/ 下的接口
（见 app.py 的 anti_csrf）。判断"哪一格填什么"用的是和 MCP 工具同一个 plan()。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from core.profile_storage import load_personal_profile

EXTENSION_ID = "ojaapcocccendgphoehaamchlchjfmok"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
EXT_PREFIX = "/api/ext/"

router = APIRouter(prefix="/api/ext")


class PlanRequest(BaseModel):
    scan: Any  # scan.js 的压缩结果（字符串），或已经展开的格子列表
    sensitive: bool = False  # 插件里"敏感信息也填"开关
    track_id: str | None = None  # 侧边栏选的"这件事"（spec 007）：trip.* 的格子用它的行程信息


def _trip_of(track_id: str | None):
    """选了"这件事"时返回它的行程信息；没选返回 None；id 不存在 404。"""
    if not track_id:
        return None
    import re

    from core.tracks import TrackNotFoundError, load_track

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", track_id):  # 不合法的 id 不会拼成别的路径
        raise HTTPException(status_code=404, detail=f"找不到这件办事：{track_id}")
    try:
        return load_track(config.get_materials_root(), track_id).trip
    except (TrackNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=f"找不到这件办事：{track_id}") from e


@router.get("/status")
def ext_status() -> dict:
    return {"ok": True, "extension_id": EXTENSION_ID}


def _guide_hosts(guide_id: str) -> set[str]:
    """攻略步骤里官网链接的域名。只读链接，不做完整校验；文件坏了返回空集合，不影响列表。"""
    from urllib.parse import urlparse

    import yaml

    try:
        raw = yaml.safe_load((config.COMMUNITY_DIR / "guides" / f"{guide_id}.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    return {
        (urlparse(str(link.get("url") or "")).hostname or "").lower()
        for step in raw.get("steps") or [] for link in (step or {}).get("links") or [] if isinstance(link, dict)
    } - {""}


@router.get("/tracks")
def ext_tracks(host: str = "") -> dict:
    """侧边栏「这件事」下拉框：正在办的事（没办完的），以及按网址猜的一件（spec 007）。

    猜法：这件事的攻略步骤里有官网链接和当前网址同域名（或它的上级域名）的；有好几件时取最近创建的。
    """
    from core.tracks import load_tracks

    host = (host or "").lower().split(":")[0]
    items, guess = [], None
    for t in sorted(load_tracks(config.get_materials_root()), key=lambda t: t.created, reverse=True):
        if t.completed:
            continue
        items.append({"id": t.id, "title": t.title})
        if guess or not host:
            continue
        hosts = _guide_hosts(t.guide)
        if any(h and (host == h or host.endswith("." + h) or h.endswith("." + host)) for h in hosts):
            guess = t.id
    return {"tracks": items, "guess": guess}


@router.get("/site-policy")
def ext_site_policy(host: str) -> dict:
    from form_engine.sites import default_site_policies, policy_for

    return policy_for(host, default_site_policies())


@router.post("/plan")
def ext_plan(body: PlanRequest) -> dict:
    from form_engine.match import ScanError, default_dictionary, expand_scan, plan, profile_leaves
    from form_engine.sites import site_date_format

    try:
        fields = expand_scan(body.scan)
    except ScanError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    allow = [p for p, leaf in profile_leaves().items() if leaf.sensitive] if body.sensitive else []
    result = plan(fields, load_personal_profile(config.get_materials_root()), default_dictionary(), allow,
                  site_date_format(fields), trip=_trip_of(body.track_id))
    result.pop("script")  # 插件自带填写脚本，只要计划
    return result


# ---- 第三版：存进基本信息（页面上已经填好的内容 → 基本信息，用户在侧边栏勾选确认后才写） ----

class CaptureRequest(BaseModel):
    scan: Any
    values: dict[str, str]  # {"格子编号": 页面上的文字}，由插件的 engine/read.js 读出
    track_id: str | None = None  # 选了"这件事"时，trip.* 的差异也列出来（spec 007）


class CaptureItem(BaseModel):
    path: str
    value: Any = None
    action: str = "set"  # "set" 写值；"none" 记为"没有"


class ApplyRequest(BaseModel):
    items: list[CaptureItem]
    track_id: str | None = None  # trip.* 的项写进这件办事


@router.post("/capture")
def ext_capture(body: CaptureRequest) -> dict:
    """只算建议，不写文件。"""
    from form_engine.capture import suggest
    from form_engine.match import ScanError, default_dictionary, expand_scan
    from form_engine.sites import site_date_format

    try:
        fields = expand_scan(body.scan)
    except ScanError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    profile = load_personal_profile(config.get_materials_root())
    return {"items": suggest(fields, body.values, profile, default_dictionary(), site_date_format(fields),
                             trip=_trip_of(body.track_id))}


@router.post("/capture/apply")
def ext_capture_apply(body: ApplyRequest) -> dict:
    """把用户勾选的建议写进基本信息；trip.* 的项写进选中的这件办事（spec 007）。

    先全部校验，有一项不合法就一项都不写。
    """
    from pydantic import ValidationError

    from core.profile_storage import confirm_profile_none, preview_profile_fields, update_profile_fields
    from core.tracks import load_track, save_track
    from core.trip import merge_trip
    from form_engine.capture import to_changes
    from form_engine.match import TRIP

    if not body.items:
        raise HTTPException(status_code=422, detail="没有要存的内容")
    root = config.get_materials_root()
    try:
        groups, none = to_changes([it.model_dump() for it in body.items])
        trip_changes = groups.pop(TRIP, None)
        if trip_changes is not None and not body.track_id:
            raise HTTPException(status_code=422, detail="行程信息要先在侧边栏选「这件事」")
        track = None
        if trip_changes is not None:
            _trip_of(body.track_id)  # 不存在就 404
            track = load_track(root, body.track_id)
            new_trip = merge_trip(track.trip, trip_changes)
        for group, changes in groups.items():
            preview_profile_fields(root, group, changes)
    except KeyError as e:
        raise HTTPException(status_code=422, detail=f"没有这个字段：{e.args[0]}") from e
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"有一项的值不合法，什么都没存：{e.errors()[0].get('msg')}") from e
    if none:
        try:
            confirm_profile_none(root, none)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    for group, changes in groups.items():
        update_profile_fields(root, group, changes)
    if track is not None:
        track.trip = new_trip
        save_track(root, track)
    return {"saved": len(body.items)}

