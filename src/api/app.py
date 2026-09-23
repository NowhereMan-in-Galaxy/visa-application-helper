"""本地 Web 服务入口。

启动方式（仓库根目录下）：
    uv run uvicorn api.app:app --app-dir src --reload

然后浏览器打开 http://127.0.0.1:8000 。
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import COMMUNITY_DIR, MATERIALS_INDEX_DIR, REPO_ROOT, get_materials_root
from core.guides import Guide, GuideLoadResult, load_all_guides
from core.material_types import Vocabulary, VocabularyError, load_vocabulary
from core.export import export_track
from core.tracks import (
    Track,
    TrackNotFoundError,
    TrackView,
    compute_track_view,
    create_track,
    load_track,
    load_tracks,
    save_track,
    sync_completion,
)
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
    material_type: str | None = None,
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
        material_type=material_type,
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


# ---------- 流程攻略（共享区）+ 我的办事（个人区），见 specs/002-guide-to-track ----------
#
# 攻略、词表、Track 每次请求都重新读文件：文件都很小，这样改完 YAML 刷新页面就能看到效果，
# 不用重启服务——这对"大家共同维护攻略"的贡献者尤其重要。


class GuideSummary(BaseModel):
    id: str
    file: str
    title: str | None
    category: str | None
    summary: str | None
    updated: date | None
    requirement_count: int
    step_count: int
    valid: bool
    errors: list[str]


class GuideDetail(BaseModel):
    summary: GuideSummary
    # 用一个"空的、没保存的 Track"算出来的预览：还没开始办，就能看到你已经有哪些材料
    preview: TrackView | None


class TrackSummary(BaseModel):
    id: str
    title: str
    guide_id: str
    category: str | None
    created: date
    deadline: date | None
    completed: date | None
    elapsed_days: int | None
    progress_ready: int | None
    progress_total: int | None
    next_step_title: str | None
    error: str | None


class TrackCreate(BaseModel):
    guide: str
    title: str | None = None
    deadline: date | None = None


class FactUpdate(BaseModel):
    value: str | None


class DoneUpdate(BaseModel):
    done: bool


class MatchUpdate(BaseModel):
    confirmed: bool


def _vocabulary() -> Vocabulary:
    try:
        return load_vocabulary(COMMUNITY_DIR / "material_types.yaml")
    except VocabularyError as e:
        raise HTTPException(status_code=500, detail=f"共享词表有错误：{e}") from e


def _guide_results() -> tuple[Vocabulary, list[GuideLoadResult]]:
    vocab = _vocabulary()
    return vocab, load_all_guides(COMMUNITY_DIR / "guides", vocab)


def _summarize(result: GuideLoadResult) -> GuideSummary:
    g = result.guide
    return GuideSummary(
        id=g.id if g else result.path.stem,
        file=f"community/guides/{result.path.name}",
        title=g.title if g else None,
        category=g.category if g else None,
        summary=g.summary if g else None,
        updated=g.updated if g else None,
        requirement_count=len(g.requirements) if g else 0,
        step_count=len(g.steps) if g else 0,
        valid=result.valid,
        errors=result.errors,
    )


def _valid_guide(guide_id: str) -> tuple[Vocabulary, Guide]:
    vocab, results = _guide_results()
    for r in results:
        if r.path.stem == guide_id:
            if not r.valid:
                raise HTTPException(status_code=422, detail=f"攻略 {guide_id} 没有通过校验：" + "；".join(r.errors))
            return vocab, r.guide
    raise HTTPException(status_code=404, detail=f"没有找到攻略：{guide_id}")


def _track_view(track: Track) -> TrackView:
    vocab, guide = _valid_guide(track.guide)
    records = load_material_records(MATERIALS_INDEX_DIR)
    return compute_track_view(guide, track, records, vocab, date.today())


def _save_track(track: Track) -> TrackView:
    """保存前按最新状态维护"办完日期"，再返回新视图。所有会改变步骤完成情况的写操作都走这里。"""
    view = _track_view(track)
    before = track.completed
    sync_completion(track, view, date.today())
    save_track(get_materials_root(), track)
    return _track_view(track) if track.completed != before else view


def _load_track_or_404(track_id: str) -> Track:
    try:
        return load_track(get_materials_root(), track_id)
    except TrackNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"没有找到这件办事：{track_id}") from e


@app.get("/api/guides", response_model=list[GuideSummary])
def list_guides() -> list[GuideSummary]:
    _, results = _guide_results()
    return [_summarize(r) for r in results]


@app.get("/api/guides/{guide_id}", response_model=GuideDetail)
def get_guide(guide_id: str) -> GuideDetail:
    vocab, results = _guide_results()
    for r in results:
        if r.path.stem == guide_id:
            preview = None
            if r.valid:
                blank = Track(id="preview", guide=r.guide.id, title=r.guide.title, created=date.today())
                records = load_material_records(MATERIALS_INDEX_DIR)
                preview = compute_track_view(r.guide, blank, records, vocab, date.today())
            return GuideDetail(summary=_summarize(r), preview=preview)
    raise HTTPException(status_code=404, detail=f"没有找到攻略：{guide_id}")


@app.get("/api/tracks", response_model=list[TrackSummary])
def list_tracks() -> list[TrackSummary]:
    summaries = []
    for track in load_tracks(get_materials_root()):
        base = dict(
            id=track.id, title=track.title, guide_id=track.guide, created=track.created,
            deadline=track.deadline, completed=track.completed,
        )
        try:
            view = _track_view(track)
            _, guide = _valid_guide(track.guide)
        except HTTPException as e:
            # 攻略被删了或改坏了：这件办事照样列出来，只是标上原因，不让它从列表里"凭空消失"
            summaries.append(TrackSummary(
                **base, category=None, elapsed_days=None,
                progress_ready=None, progress_total=None, next_step_title=None, error=e.detail,
            ))
            continue
        next_title = next((s.title for s in view.steps if s.id == view.next_step), None)
        summaries.append(TrackSummary(
            **base, category=guide.category, elapsed_days=view.elapsed_days,
            progress_ready=view.progress_ready, progress_total=view.progress_total,
            next_step_title=next_title, error=None,
        ))
    return summaries


@app.post("/api/tracks", response_model=TrackView)
def create_track_endpoint(payload: TrackCreate) -> TrackView:
    _, guide = _valid_guide(payload.guide)
    title = payload.title.strip() if payload.title and payload.title.strip() else None
    track = create_track(get_materials_root(), guide, date.today(), title=title, deadline=payload.deadline)
    return _track_view(track)


@app.get("/api/tracks/{track_id}", response_model=TrackView)
def get_track(track_id: str) -> TrackView:
    return _track_view(_load_track_or_404(track_id))


@app.put("/api/tracks/{track_id}/facts/{fact}", response_model=TrackView)
def update_track_fact(track_id: str, fact: str, payload: FactUpdate) -> TrackView:
    track = _load_track_or_404(track_id)
    _, guide = _valid_guide(track.guide)
    if fact not in guide.facts:
        raise HTTPException(status_code=404, detail=f"这份攻略没有问题 {fact}")
    if payload.value is None:
        track.facts.pop(fact, None)
    elif payload.value not in guide.facts[fact].options:
        raise HTTPException(status_code=422, detail=f"{payload.value!r} 不是这个问题的选项")
    else:
        track.facts[fact] = payload.value
    return _save_track(track)


@app.put("/api/tracks/{track_id}/steps/{step}", response_model=TrackView)
def update_track_step(track_id: str, step: str, payload: DoneUpdate) -> TrackView:
    track = _load_track_or_404(track_id)
    _, guide = _valid_guide(track.guide)
    if not any(s.id == step for s in guide.steps):
        raise HTTPException(status_code=404, detail=f"这份攻略没有步骤 {step}")
    done = [s for s in track.done_steps if s != step]
    track.done_steps = done + [step] if payload.done else done
    return _save_track(track)


@app.put("/api/tracks/{track_id}/checks/{check}", response_model=TrackView)
def update_track_check(track_id: str, check: str, payload: DoneUpdate) -> TrackView:
    track = _load_track_or_404(track_id)
    _, guide = _valid_guide(track.guide)
    if not any(c.id == check for c in guide.checks):
        raise HTTPException(status_code=404, detail=f"这份攻略没有核对项 {check}")
    done = [c for c in track.done_checks if c != check]
    track.done_checks = done + [check] if payload.done else done
    save_track(get_materials_root(), track)
    return _track_view(track)


@app.put("/api/tracks/{track_id}/matches/{requirement}", response_model=TrackView)
def update_track_match(track_id: str, requirement: str, payload: MatchUpdate) -> TrackView:
    """confirmed=true：把当前候选记录写进 matches；false：取消确认。候选由核心库算，前端不能随便指定记录。"""
    track = _load_track_or_404(track_id)
    if not payload.confirmed:
        track.matches.pop(requirement, None)
    else:
        view = _track_view(track)
        req = next((r for r in view.requirements if r.id == requirement), None)
        if req is None:
            raise HTTPException(status_code=404, detail=f"这份攻略没有需求 {requirement}")
        if not req.records:
            raise HTTPException(status_code=422, detail="材料库里还没有能满足这条需求的记录")
        track.matches[requirement] = [r.id for r in req.records]
    save_track(get_materials_root(), track)
    return _track_view(track)


class ExportResponse(BaseModel):
    folder: str
    copied: list[str]
    missing_files: list[str]
    pending: list[str]


@app.post("/api/tracks/{track_id}/requirements/{requirement}/upload", response_model=TrackView)
async def upload_for_requirement(
    track_id: str,
    requirement: str,
    file: UploadFile = File(...),
    obtained_date: date | None = Form(None),
    part: str | None = Form(None),
    sublabel: str | None = Form(None),
) -> TrackView:
    """在办事页面直接为一条缺失/过期的需求上传材料：新建一条材料记录（进个人材料库，别的办事也能复用），
    并在材料凑齐时自动确认给这条需求。组合类型（例如护照全部页）要用 part 指明上传的是哪一部分。"""
    track = _load_track_or_404(track_id)
    vocab, _ = _valid_guide(track.guide)
    view = _track_view(track)
    req = next((r for r in view.requirements if r.id == requirement), None)
    if req is None:
        raise HTTPException(status_code=404, detail=f"这份攻略没有需求 {requirement}")
    if req.state == "not_applicable":
        raise HTTPException(status_code=422, detail="这条材料对你不适用，不需要上传")
    if req.material_type is None:
        raise HTTPException(status_code=422, detail="词表还不认识这种材料，暂时没法归档；请先补充 community/material_types.yaml")
    parts = vocab.types[req.material_type].parts
    if parts:
        if part not in parts:
            raise HTTPException(status_code=422, detail=f"这是组合材料，请指明上传的是哪一部分：{', '.join(parts)}")
        target_type = part
    else:
        target_type = req.material_type
    mtype = vocab.types[target_type]

    await _create_material(
        belongs_to=None,
        category=mtype.category or MaterialCategory.OTHER,
        type_=mtype.name,
        obtained_date=obtained_date or date.today(),
        sublabel=sublabel.strip() if sublabel and sublabel.strip() else None,
        validity_days=None,
        recommended_update_interval_days=None,
        recommended_update_day_of_month=None,
        file=file,
        material_type=target_type,
    )

    # 刚上传的是最新的一份：丢掉旧的确认，按最新候选重新判断；凑齐了就直接确认给这条需求
    track.matches.pop(requirement, None)
    refreshed = next(r for r in _track_view(track).requirements if r.id == requirement)
    if refreshed.state == "unconfirmed":
        track.matches[requirement] = [r.id for r in refreshed.records]
    save_track(get_materials_root(), track)
    return _track_view(track)


@app.post("/api/tracks/{track_id}/export", response_model=ExportResponse)
def export_track_materials(track_id: str) -> ExportResponse:
    """把已确认（状态为"已有"）的材料复制到 <材料根目录>/exports/<办事 id>-<时间>/，附一份清单。"""
    track = _load_track_or_404(track_id)
    view = _track_view(track)
    records = load_material_records(MATERIALS_INDEX_DIR)
    result = export_track(view, records, get_materials_root(), datetime.now())
    return ExportResponse(
        folder=str(result.folder), copied=result.copied,
        missing_files=result.missing_files, pending=result.pending,
    )


# 前端静态页面：web/index.html 等。放在所有 /api/... 路由之后注册，
# 这样 "/" 会命中静态文件，不会被误判成某个 API 路径。
app.mount("/", StaticFiles(directory=REPO_ROOT / "web", html=True), name="web")
