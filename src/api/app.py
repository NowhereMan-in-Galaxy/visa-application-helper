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
from core.pdf_merge import UnsupportedPageFormatError, append_page
from core.status import compute_status
from core.storage import (
    RecordIdConflictError,
    load_material_records,
    load_materials_for_application,
    load_visa_applications,
    overwrite_material_record,
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
    """给"办事材料准备" tab 用——只看挂在这次申请下的材料（financial_snapshot / employment_doc）。"""
    _require_application(application_id)
    records = load_materials_for_application(MATERIALS_INDEX_DIR, application_id)
    today = date.today()
    return [_to_material_view(record, today) for record in records]


@app.get("/api/materials", response_model=list[MaterialView])
def list_all_materials(category: MaterialCategory | None = None) -> list[MaterialView]:
    """给"个人材料" tab 用——不看 belongs_to，跨所有申请聚合展示（证件类本来就不该按申请分）。"""
    records = load_material_records(MATERIALS_INDEX_DIR)
    if category is not None:
        records = [r for r in records if r.category == category]
    today = date.today()
    return [_to_material_view(record, today) for record in records]


async def _create_material(
    *,
    belongs_to: str | None,
    category: MaterialCategory,
    type_: str,
    obtained_date: date,
    sublabel: str | None,
    validity_days: int | None,
    recommended_update_interval_days: int | None,
    recommended_update_day_of_month: int | None,
    file: UploadFile | None,
) -> MaterialView:
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
        type=type_,
        belongs_to=belongs_to,
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
    """User Story 4（FR-012）："办事材料准备" tab 新增一条挂在这次申请下的材料记录。"""
    _require_application(application_id)
    return await _create_material(
        belongs_to=application_id,
        category=category,
        type_=type,
        obtained_date=obtained_date,
        sublabel=sublabel,
        validity_days=validity_days,
        recommended_update_interval_days=recommended_update_interval_days,
        recommended_update_day_of_month=recommended_update_day_of_month,
        file=file,
    )


@app.post("/api/materials", response_model=MaterialView)
async def create_personal_material(
    category: MaterialCategory = Form(...),
    type: str = Form(...),  # noqa: A002
    obtained_date: date = Form(...),
    sublabel: str | None = Form(None),
    validity_days: int | None = Form(None),
    recommended_update_interval_days: int | None = Form(None),
    recommended_update_day_of_month: int | None = Form(None),
    file: UploadFile | None = File(None),
) -> MaterialView:
    """"个人材料" tab 新增一条不挂靠任何具体申请的材料记录（证件类）。"""
    return await _create_material(
        belongs_to=None,
        category=category,
        type_=type,
        obtained_date=obtained_date,
        sublabel=sublabel,
        validity_days=validity_days,
        recommended_update_interval_days=recommended_update_interval_days,
        recommended_update_day_of_month=recommended_update_day_of_month,
        file=file,
    )


@app.post("/api/materials/{material_id}/append-page", response_model=MaterialView)
async def append_material_page(material_id: str, file: UploadFile = File(...)) -> MaterialView:
    """把新扫描的一页（图片或 PDF）追加进这条材料记录已有的 PDF 末尾。

    典型场景：护照盖章页那份 PDF 已经有好几页旧章，出国一趟回来又盖了新章，拍照/扫描
    上传新的这一页，追加进同一份文件——不新建一条记录，也不需要用户自己去合并 PDF。
    """
    all_records = load_material_records(MATERIALS_INDEX_DIR)
    record = next((r for r in all_records if r.id == material_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"没有找到材料记录：{material_id}")
    if record.file_ref is None:
        raise HTTPException(
            status_code=400, detail="这条记录还没有对应文件，没法追加页——先新建一条记录并上传文件"
        )
    if not record.file_ref.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只能给 PDF 文件追加页，这条记录对应的不是 PDF")

    existing_path = get_materials_root() / record.file_ref
    if not existing_path.is_file():
        raise HTTPException(status_code=404, detail=f"索引指向的文件在材料根目录下不存在：{record.file_ref}")

    content = await file.read()
    try:
        append_page(existing_path, file.filename or "", content)
    except UnsupportedPageFormatError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # 追加了新页，obtained_date 更新成今天——代表这条材料"最新一次更新"的时间，
    # 跟着这个日期算出来的状态/更新提醒也会跟着重新走一遍（见 core/status.py、update_cadence.py）。
    record.obtained_date = date.today()
    overwrite_material_record(MATERIALS_INDEX_DIR, record)

    return _to_material_view(record, date.today())


@app.get("/api/personal-profile", response_model=PersonalProfile)
def get_personal_profile() -> PersonalProfile:
    return load_personal_profile(get_materials_root())


class TravelHistoryCreate(BaseModel):
    country: str | None = None
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


@app.put("/api/personal-profile/travel-history/{index}", response_model=PersonalProfile)
def update_travel_history_entry(index: int, entry: TravelHistoryCreate) -> PersonalProfile:
    """补充/修正一条已有出行记录——典型场景：批量导入时国家留了空，用户现在把它填上。

    `index` 是这条记录在 travel_history 列表里的位置（从 0 开始，按 materials_root/
    personal-profile.yaml 里存的顺序，不是前端排序展示后的顺序——前端负责把原始位置带回来）。
    """
    materials_root = get_materials_root()
    profile = load_personal_profile(materials_root)
    if not 0 <= index < len(profile.travel_history):
        raise HTTPException(status_code=404, detail=f"没有第 {index} 条出行记录")
    profile.travel_history[index] = TravelHistoryEntry(**entry.model_dump())
    save_personal_profile(materials_root, profile)
    return profile


# 前端静态页面：web/index.html 等。放在所有 /api/... 路由之后注册，
# 这样 "/" 会命中静态文件，不会被误判成某个 API 路径。
app.mount("/", StaticFiles(directory=REPO_ROOT / "web", html=True), name="web")
