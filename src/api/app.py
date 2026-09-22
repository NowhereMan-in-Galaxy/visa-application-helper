"""本地 Web 服务入口（User Story 1：按签证申请浏览材料，看状态）。

启动方式（仓库根目录下）：
    uv run uvicorn api.app:app --app-dir src --reload

然后浏览器打开 http://127.0.0.1:8000 。
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import MATERIALS_INDEX_DIR, REPO_ROOT
from core.models import MaterialCategory, MaterialStatus, VisaApplication
from core.status import compute_status
from core.storage import load_materials_for_application, load_visa_applications
from core.update_cadence import compute_update_reminder

app = FastAPI(title="材料资料库")


class MaterialView(BaseModel):
    """材料记录 + 核心库算出来的状态，一起返回给前端，前端不用再自己算一遍。"""

    id: str
    category: MaterialCategory
    type: str
    sublabel: str | None
    obtained_date: date | None
    status: MaterialStatus
    days_until_expiry: int | None
    update_due_date: date | None
    update_days_until_due: int | None
    update_overdue: bool | None


@app.get("/api/visa-applications", response_model=list[VisaApplication])
def list_visa_applications() -> list[VisaApplication]:
    return load_visa_applications(MATERIALS_INDEX_DIR)


@app.get(
    "/api/visa-applications/{application_id}/materials",
    response_model=list[MaterialView],
)
def list_materials(application_id: str) -> list[MaterialView]:
    applications = load_visa_applications(MATERIALS_INDEX_DIR)
    if not any(app_.id == application_id for app_ in applications):
        raise HTTPException(status_code=404, detail=f"没有找到签证申请：{application_id}")

    records = load_materials_for_application(MATERIALS_INDEX_DIR, application_id)
    today = date.today()

    views: list[MaterialView] = []
    for record in records:
        status_result = compute_status(record, today)
        reminder = compute_update_reminder(record, today)
        views.append(
            MaterialView(
                id=record.id,
                category=record.category,
                type=record.type,
                sublabel=record.sublabel,
                obtained_date=record.obtained_date,
                status=status_result.status,
                days_until_expiry=status_result.days_until_expiry,
                update_due_date=reminder.due_date if reminder else None,
                update_days_until_due=reminder.days_until_due if reminder else None,
                update_overdue=reminder.overdue if reminder else None,
            )
        )
    return views


# 前端静态页面：web/index.html 等。放在所有 /api/... 路由之后注册，
# 这样 "/" 会命中静态文件，不会被误判成某个 API 路径。
app.mount("/", StaticFiles(directory=REPO_ROOT / "web", html=True), name="web")
