"""本地 Web 服务入口。

启动方式（仓库根目录下）：
    uv run uvicorn api.app:app --app-dir src --reload

然后浏览器打开 http://127.0.0.1:8000 。
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import MATERIALS_INDEX_DIR, REPO_ROOT, get_materials_root
from core.models import (
    MaterialCategory,
    MaterialRecord,
    MaterialStatus,
    PersonalProfile,
    TravelHistoryEntry,
    VisaApplication,
)
from core.profile_storage import load_personal_profile, save_personal_profile
from core.status import compute_status
from core.storage import (
    RecordIdConflictError,
    load_materials_for_application,
    load_visa_applications,
    save_material_record,
)
from core.update_cadence import compute_update_reminder
from core.uploads import UploadConflictError, save_uploaded_file

app = FastAPI(title="材料资料库")


class MaterialView(BaseModel):
    """材料记录 + 核心库算出来的状态，一起返回给前端，前端不用再自己算一遍。"""

    id: str
    category: MaterialCategory
    type: str
    sublabel: str | None
    obtained_date: date | None
    file_ref: str | None
    status: MaterialStatus
    days_until_expiry: int | None
    update_due_date: date | None
    update_days_until_due: int | None
    update_overdue: bool | None


def _to_material_view(record: MaterialRecord, today: date) -> MaterialView:
    status_result = compute_status(record, today)
    reminder = compute_update_reminder(record, today)
    return MaterialView(
        id=record.id,
        category=record.category,
        type=record.type,
        sublabel=record.sublabel,
        obtained_date=record.obtained_date,
        file_ref=record.file_ref,
        status=status_result.status,
        days_until_expiry=status_result.days_until_expiry,
        update_due_date=reminder.due_date if reminder else None,
        update_days_until_due=reminder.days_until_due if reminder else None,
        update_overdue=reminder.overdue if reminder else None,
    )


def _require_application(application_id: str) -> None:
    applications = load_visa_applications(MATERIALS_INDEX_DIR)
    if not any(app_.id == application_id for app_ in applications):
        raise HTTPException(status_code=404, detail=f"没有找到签证申请：{application_id}")


@app.get("/api/visa-applications", response_model=list[VisaApplication])
def list_visa_applications() -> list[VisaApplication]:
    return load_visa_applications(MATERIALS_INDEX_DIR)


@app.get(
    "/api/visa-applications/{application_id}/materials",
    response_model=list[MaterialView],
)
def list_materials(application_id: str) -> list[MaterialView]:
    _require_application(application_id)
    records = load_materials_for_application(MATERIALS_INDEX_DIR, application_id)
    today = date.today()
    return [_to_material_view(record, today) for record in records]


@app.post(
    "/api/visa-applications/{application_id}/materials",
    response_model=MaterialView,
)
async def create_material(
    application_id: str,
    category: MaterialCategory = Form(...),
    type: str = Form(...),  # noqa: A002 - 跟前端表单字段名对齐
    obtained_date: date = Form(...),
    sublabel: str | None = Form(None),
    validity_days: int | None = Form(None),
    recommended_update_interval_days: int | None = Form(None),
    recommended_update_day_of_month: int | None = Form(None),
    file: UploadFile | None = File(None),
) -> MaterialView:
    """User Story 4（FR-012）：前端新增一条材料记录，可选附带上传文件。"""
    _require_application(application_id)

    # 用 "类别-日期-随机后缀" 做 id：日期方便人眼在 materials_index/records/ 里按时间找到它，
    # 随机后缀保证不会跟已有记录撞 id（撞了 save_material_record 也会拒绝，不会覆盖）。
    record_id = f"{category.value}-{obtained_date.isoformat()}-{uuid4().hex[:8]}"

    file_ref: str | None = None
    if file is not None and file.filename:
        content = await file.read()
        try:
            file_ref = save_uploaded_file(
                get_materials_root(), category.value, record_id, file.filename, content
            )
        except UploadConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    record = MaterialRecord(
        id=record_id,
        category=category,
        type=type,
        belongs_to=application_id,
        obtained_date=obtained_date,
        sublabel=sublabel,
        validity_days=validity_days,
        recommended_update_interval_days=recommended_update_interval_days,
        recommended_update_day_of_month=recommended_update_day_of_month,
        file_ref=file_ref,
    )
    try:
        save_material_record(MATERIALS_INDEX_DIR, record)
    except RecordIdConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return _to_material_view(record, date.today())


@app.get("/api/personal-profile", response_model=PersonalProfile)
def get_personal_profile() -> PersonalProfile:
    return load_personal_profile(get_materials_root())


class TravelHistoryCreate(BaseModel):
    country: str
    entry_date: date
    exit_date: date | None = None
    purpose: str | None = None


@app.post("/api/personal-profile/travel-history", response_model=PersonalProfile)
def add_travel_history_entry(entry: TravelHistoryCreate) -> PersonalProfile:
    """User Story 4（FR-013）：追加一条出行记录，写回材料根目录下的 PersonalProfile 文件。"""
    materials_root = get_materials_root()
    profile = load_personal_profile(materials_root)
    profile.travel_history.append(TravelHistoryEntry(**entry.model_dump()))
    save_personal_profile(materials_root, profile)
    return profile


# 前端静态页面：web/index.html 等。放在所有 /api/... 路由之后注册，
# 这样 "/" 会命中静态文件，不会被误判成某个 API 路径。
app.mount("/", StaticFiles(directory=REPO_ROOT / "web", html=True), name="web")
