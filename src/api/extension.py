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
