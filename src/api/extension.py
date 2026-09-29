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


@router.get("/status")
def ext_status() -> dict:
    return {"ok": True, "extension_id": EXTENSION_ID}


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
                  site_date_format(fields))
    result.pop("script")  # 插件自带填写脚本，只要计划
    return result


# ---- 第三版：存进基本信息（页面上已经填好的内容 → 基本信息，用户在侧边栏勾选确认后才写） ----

class CaptureRequest(BaseModel):
    scan: Any
    values: dict[str, str]  # {"格子编号": 页面上的文字}，由插件的 engine/read.js 读出


class CaptureItem(BaseModel):
    path: str
    value: Any = None
    action: str = "set"  # "set" 写值；"none" 记为"没有"


class ApplyRequest(BaseModel):
    items: list[CaptureItem]


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
    return {"items": suggest(fields, body.values, profile, default_dictionary(), site_date_format(fields))}


@router.post("/capture/apply")
def ext_capture_apply(body: ApplyRequest) -> dict:
    """把用户勾选的建议写进基本信息。先全部校验，有一项不合法就一项都不写。"""
    from pydantic import ValidationError

    from core.profile_storage import confirm_profile_none, preview_profile_fields, update_profile_fields
    from form_engine.capture import to_changes

    if not body.items:
        raise HTTPException(status_code=422, detail="没有要存的内容")
    root = config.get_materials_root()
    try:
        groups, none = to_changes([it.model_dump() for it in body.items])
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
    return {"saved": len(body.items)}

