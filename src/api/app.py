"""本地 Web 服务入口。

启动方式（仓库根目录下）：
    uv run uvicorn api.app:app --app-dir src --reload

然后浏览器打开 http://127.0.0.1:8000 。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import COMMUNITY_DIR, MATERIALS_INDEX_DIR, REPO_ROOT, get_materials_root
from core.guides import Guide, GuideLoadResult, load_all_guides
from core.material_types import Vocabulary, VocabularyError, load_vocabulary
import core.adjustments as adj
from core.adjustments import AdjustmentError
from core.export import export_track
from core.forms import load_all_forms
from core.windows import calendar_ics
from core.tracks import (
    Pitfall,
    apply_adjustments,
    Track,
    TrackNotFoundError,
    TrackView,
    compute_track_view,
    set_fact_value,
    set_step_done,
    create_track,
    load_track,
    load_tracks,
    record_type,
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


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """让浏览器每次都向服务器确认页面和脚本是否更新（有 ETag，没变化时只回 304，几乎不花时间）。

    否则改完 web/ 下的文件，浏览器可能继续用缓存里的旧脚本，看起来像"改了没生效"。
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- 防跨站请求（CSRF）/ DNS 重绑定 ----------
#
# 威胁模型：本地服务没有登录鉴权，浏览器里打开的任何网页（包括恶意网页、被 DNS 重绑定劫持指向
# 本机的域名）原则上都能直接向 127.0.0.1:8000 发请求。下面这个中间件挡的是"浏览器里的网页发起
# 的跨站请求"；挡不住本机上能直接发 HTTP 请求的其他进程（curl、脚本、本地 Agent 进程）——这些
# 进程根本不会带 Origin / Sec-Fetch-Site，属于"两个头都没有 → 放行"那一支，本来就在信任边界内
# （spec 002 里 B3 的安全前提对此有说明）。

# Host 头去掉端口后，允许出现的值（大小写不敏感）。testserver 是 FastAPI TestClient 的默认 Host，
# 只在测试环境出现，不影响真实浏览器请求。
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
# 没写端口时，各协议的默认端口——用来判断 "http://127.0.0.1" 和 Host "127.0.0.1:80" 是不是同一个源。
_DEFAULT_PORTS = {"http": 80, "https": 443}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _split_hostport(hostport: str) -> tuple[str, str | None] | None:
    """把 `host[:port]` 或 `[ipv6][:port]` 拆成 `(host, port字符串或None)`。

    host 统一转小写、去掉 IPv6 的方括号，这样 `[::1]` 和裸的 `::1` 按同一个值比较。
    解析失败（例如方括号不闭合）返回 None。
    """
    hostport = hostport.strip()
    if not hostport:
        return None
    if hostport.startswith("["):
        end = hostport.find("]")
        if end == -1:
            return None
        host = hostport[1:end].lower()
        rest = hostport[end + 1 :]
        if rest == "":
            return host, None
        if rest.startswith(":"):
            return host, rest[1:]
        return None
    if hostport.count(":") == 1:
        # 正好一个冒号：当成 "host:port"（IPv6 裸地址至少有两个冒号，不会走到这支）。
        host, _, port = hostport.partition(":")
        return host.lower(), port
    return hostport.lower(), None


def _origin_tuple(scheme: str, hostport: str) -> tuple[str, str, int] | None:
    """算出 `(scheme, host, port)` 形式的"源"，缺端口时按 scheme 补默认端口，便于精确比较。"""
    split = _split_hostport(hostport)
    if split is None:
        return None
    host, port_str = split
    if port_str:
        try:
            port = int(port_str)
        except ValueError:
            return None
    else:
        port = _DEFAULT_PORTS.get(scheme.lower())
        if port is None:
            return None
    return scheme.lower(), host, port


def _parse_origin_header(value: str) -> tuple[str, str, int] | None:
    """解析形如 `http://127.0.0.1:8000` 的 Origin 头；解析不出来（例如 `null`）返回 None。"""
    scheme, sep, rest = value.partition("://")
    if not sep or not scheme:
        return None
    hostport = rest.split("/", 1)[0]
    if not hostport:
        return None
    return _origin_tuple(scheme, hostport)


def _forbidden(reason: str) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": reason})


@app.middleware("http")
async def anti_csrf(request: Request, call_next):
    """挡跨站写请求（CSRF）和 DNS 重绑定，规则见 specs/002-guide-to-track/spec.md 的 B3 安全前提。

    1. 所有请求：Host 头去掉端口后必须在 `_ALLOWED_HOSTS` 里，否则 403（防 DNS 重绑定——如果
       攻击者让某个外部域名解析到 127.0.0.1，浏览器发过来的 Host 头会是那个外部域名，不在白名单
       里，直接拒绝）。
    2. 写请求（POST/PUT/PATCH/DELETE）：
       - 带 Origin 头时，其 `scheme://host:port` 必须与"本次请求的 Host 头对应的源"完全一致
         （正确处理默认端口：`http://127.0.0.1` 等价于 Host `127.0.0.1:80`；`localhost` 和
         `127.0.0.1` 主机名不同，即使都指向本机也算跨源，不放行）。
       - 带 Sec-Fetch-Site 头且值为 `cross-site` 或 `same-site` 时拒绝（`localhost:3000` 对
         `localhost:8000` 主机名相同但端口不同，浏览器会标成 `same-site` 而不是 `same-origin`，
         同样要拦）。
       - 两个头都没有（curl、TestClient、本机其他进程发的请求）→ 放行，见上面的威胁模型说明。
    3. GET / HEAD / OPTIONS 只做第 1 条。
    """
    host_header = request.headers.get("host", "")
    split_host = _split_hostport(host_header)
    if split_host is None or split_host[0] not in _ALLOWED_HOSTS:
        return _forbidden(f"不接受这个 Host：{host_header!r}，可能是 DNS 重绑定攻击")

    if request.method.upper() in _UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None:
            expected = _origin_tuple(request.url.scheme, host_header)
            got = _parse_origin_header(origin)
            if got is None or got != expected:
                return _forbidden(f"跨站请求被拒绝：Origin（{origin}）与当前站点不一致")

        sec_fetch_site = request.headers.get("sec-fetch-site")
        if sec_fetch_site in ("cross-site", "same-site"):
            return _forbidden(f"跨站请求被拒绝：Sec-Fetch-Site 是 {sec_fetch_site}")

    return await call_next(request)


class MaterialView(BaseModel):
    """材料记录 + 核心库算出来的状态，一起返回给前端，前端不用再自己算一遍。"""

    id: str
    category: MaterialCategory
    type: str
    sublabel: str | None
    obtained_date: date | None
    # 编辑表单要回填当前值；不返回的话，表单里有效期一栏永远是空的，保存时会把原有有效期清掉
    validity_days: int | None
    file_ref: str | None
    for_track: str | None  # 只属于某件办事的一次性材料；None = 长期资料
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
        validity_days=record.validity_days,
        file_ref=record.file_ref,
        for_track=record.for_track,
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
    for_track: str | None = None,
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
        for_track=for_track,
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


# ---------- 新版界面「02 我的资料」用到的接口，见 specs/002-guide-to-track/tasks-parallel-1.md 任务 A ----------


class MaterialTypeSummary(BaseModel):
    key: str
    name: str
    category: MaterialCategory | None


@app.get("/api/material-types", response_model=list[MaterialTypeSummary])
def list_material_types() -> list[MaterialTypeSummary]:
    """给"新增材料"表单的 type 输入框提供候选词（datalist），来自共享词表。"""
    vocab = _vocabulary()
    return [
        MaterialTypeSummary(key=t.key, name=t.name, category=t.category)
        for t in vocab.types.values()
    ]


class MaterialUsage(BaseModel):
    track_id: str
    track_title: str
    requirement_name: str


@app.get("/api/materials/usage", response_model=dict[str, list[MaterialUsage]])
def materials_usage() -> dict[str, list[MaterialUsage]]:
    """一条材料记录被哪些"我的办事"用到——只看各 Track `matches` 里已经确认的记录

    （`matches` 本身只存确认过的匹配，见 core/tracks.py 里 Track 模型的注释），
    攻略被删了或改坏了（无效）的 Track 直接跳过，不让它报错影响整个列表。
    """
    usage: dict[str, list[MaterialUsage]] = {}
    vocab, guide_results = _guide_results()
    guides_by_id = {r.guide.id: r.guide for r in guide_results if r.valid}
    for track in load_tracks(get_materials_root()):
        guide = guides_by_id.get(track.guide)
        if guide is None:
            continue
        req_by_id = {r.id: r for r in guide.requirements}
        for requirement_id, record_ids in track.matches.items():
            requirement = req_by_id.get(requirement_id)
            if requirement is None:
                continue
            name = vocab.name_of(requirement.material_type) or requirement.raw_name or requirement.id
            for record_id in record_ids:
                usage.setdefault(record_id, []).append(
                    MaterialUsage(track_id=track.id, track_title=track.title, requirement_name=name)
                )
    return usage


class MaterialUpdate(BaseModel):
    type: str | None = None
    sublabel: str | None = None
    obtained_date: date | None = None
    validity_days: int | None = None
    # null = 转为长期资料；某件办事的 id = 改为那件办事专用
    for_track: str | None = None


@app.patch("/api/materials/{material_id}", response_model=MaterialView)
def update_material(material_id: str, payload: MaterialUpdate) -> MaterialView:
    """编辑一条已有材料记录的基本字段。

    只处理请求体里真正出现的字段（`model_fields_set`）：没提供的字段保持原样；
    `sublabel` / `validity_days` 传 `null` 表示清空；`type` 不能是空字符串。
    """
    records = load_material_records(MATERIALS_INDEX_DIR)
    record = next((r for r in records if r.id == material_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"没有找到材料记录：{material_id}")

    fields = payload.model_fields_set
    if "type" in fields:
        new_type = (payload.type or "").strip()
        if not new_type:
            raise HTTPException(status_code=422, detail="type 不能为空")
        record.type = new_type
    if "sublabel" in fields:
        record.sublabel = payload.sublabel
    if "obtained_date" in fields:
        record.obtained_date = payload.obtained_date
    if "validity_days" in fields:
        record.validity_days = payload.validity_days
    if "for_track" in fields:
        if payload.for_track is not None:
            try:
                load_track(get_materials_root(), payload.for_track)
            except TrackNotFoundError as e:
                raise HTTPException(status_code=422, detail=f"没有这件办事：{payload.for_track}") from e
        record.for_track = payload.for_track

    overwrite_material_record(MATERIALS_INDEX_DIR, record)
    return _to_material_view(record, date.today())


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
    # 最近的一条时间提醒 {date, kind, step, title}（spec §3c），首页卡片上显示"X月X日起可以办 …"
    next_reminder: dict | None = None


class TrackCreate(BaseModel):
    guide: str
    title: str | None = None
    deadline: date | None = None


class FactUpdate(BaseModel):
    value: str | None


class DoneUpdate(BaseModel):
    done: bool


class DeadlineUpdate(BaseModel):
    deadline: date | None


class MatchUpdate(BaseModel):
    confirmed: bool
    # 用户自己从"我的资料"里挑的记录 id；不传时用核心库算出的候选。
    # 组合类型（例如护照全部页）按词表 parts 的顺序每部分一条。
    records: list[str] | None = None


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


@app.get("/api/forms/{form_id}")
def get_form(form_id: str) -> dict:
    """填表指南（community/forms/<id>.yaml），给页面上的"填表指南"链接用。"""
    for r in load_all_forms(COMMUNITY_DIR / "forms"):
        if r.path.stem == form_id:
            if not r.valid:
                raise HTTPException(status_code=422, detail=f"填表指南 {form_id} 没有通过校验：" + "；".join(r.errors))
            return r.form.model_dump(mode="json")
    raise HTTPException(status_code=404, detail=f"没有找到填表指南：{form_id}")


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
            next_reminder=view.reminders[0] if view.reminders else None,
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


@app.get("/api/tracks/{track_id}/calendar.ics")
def track_calendar(track_id: str) -> Response:
    """把这件办事的时间提醒导出成日历文件（spec §3c），导入手机/电脑日历后到点会提醒。"""
    track = _load_track_or_404(track_id)
    view = _track_view(track)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = calendar_ics(track.id, view.title, view.reminders, stamp)
    return Response(
        content=body, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{track.id}.ics\""},
    )


@app.put("/api/tracks/{track_id}/deadline", response_model=TrackView)
def update_track_deadline(track_id: str, payload: DeadlineUpdate) -> TrackView:
    """设置或清除这件事的截止日期（倒排时间的输入）；见 core.tracks 的"状态计算"。"""
    track = _load_track_or_404(track_id)
    track.deadline = payload.deadline
    return _save_track(track)


@app.put("/api/tracks/{track_id}/facts/{fact}", response_model=TrackView)
def update_track_fact(track_id: str, fact: str, payload: FactUpdate) -> TrackView:
    track = _load_track_or_404(track_id)
    _, guide = _valid_guide(track.guide)
    if fact not in guide.facts:
        raise HTTPException(status_code=404, detail=f"这份攻略没有问题 {fact}")
    try:
        set_fact_value(guide, track, fact, payload.value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _save_track(track)


@app.put("/api/tracks/{track_id}/steps/{step}", response_model=TrackView)
def update_track_step(track_id: str, step: str, payload: DoneUpdate) -> TrackView:
    track = _load_track_or_404(track_id)
    _, guide = _valid_guide(track.guide)
    if not any(s.id == step for s in apply_adjustments(guide, track).steps):
        raise HTTPException(status_code=404, detail=f"这件办事里没有步骤 {step}")
    set_step_done(track, step, payload.done, date.today())
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
    """confirmed=true：确认这条需求用哪些材料；false：取消确认。

    不传 records 时用核心库算出的候选；传了 records 表示用户自己从材料库里挑（自动识别没认出来的情况，
    例如签证页和盖章页扫在同一份 PDF 里）。用户挑的记录如果词表认不出它的类型，顺手把类型记到记录上，
    下次别的办事就能自动识别；已经有明确类型的记录不改，避免一条记录被改来改去。
    """
    track = _load_track_or_404(track_id)
    if not payload.confirmed:
        track.matches.pop(requirement, None)
        save_track(get_materials_root(), track)
        return _track_view(track)

    view = _track_view(track)
    req = next((r for r in view.requirements if r.id == requirement), None)
    if req is None:
        raise HTTPException(status_code=404, detail=f"这份攻略没有需求 {requirement}")
    if payload.records is None:
        if not req.records:
            raise HTTPException(status_code=422, detail="材料库里还没有能满足这条需求的记录")
        track.matches[requirement] = [r.id for r in req.records]
    else:
        vocab = _vocabulary()
        slots = [p["key"] for p in req.parts] or ([req.material_type] if req.material_type else [None])
        if len(payload.records) != len(slots):
            raise HTTPException(status_code=422, detail=f"需要选 {len(slots)} 份材料（{'、'.join(p['name'] for p in req.parts) or req.name}）")
        by_id = {r.id: r for r in load_material_records(MATERIALS_INDEX_DIR)}
        for rid in payload.records:
            if rid not in by_id:
                raise HTTPException(status_code=404, detail=f"没有找到材料记录：{rid}")
            if rid.startswith("example-"):
                raise HTTPException(status_code=422, detail="示例记录不能用于真实的办事")
            if by_id[rid].for_track not in (None, track.id):
                raise HTTPException(status_code=422, detail="这份材料是另一件办事专用的；需要的话先在「我的资料」里把它转为长期资料")
        for rid, slot in zip(payload.records, slots):
            record = by_id[rid]
            if slot is not None and record_type(record, vocab) is None:
                record.material_type = slot
                overwrite_material_record(MATERIALS_INDEX_DIR, record)
        track.matches[requirement] = list(payload.records)
    save_track(get_materials_root(), track)
    return _track_view(track)


class PitfallCreate(BaseModel):
    text: str


class PitfallUpdate(BaseModel):
    text: str | None = None
    done: bool | None = None


def _pitfall_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="避坑点不能为空")
    if len(text) > 300:
        raise HTTPException(status_code=422, detail="避坑点太长了（最多 300 字），可以拆成几条")
    return text


@app.post("/api/tracks/{track_id}/pitfalls", response_model=TrackView)
def add_pitfall(track_id: str, payload: PitfallCreate) -> TrackView:
    """记一条自己的避坑点（只存在这件办事里，不会进共享攻略）。"""
    track = _load_track_or_404(track_id)
    track.pitfalls.append(Pitfall(id=f"p-{uuid4().hex[:8]}", text=_pitfall_text(payload.text)))
    save_track(get_materials_root(), track)
    return _track_view(track)


@app.put("/api/tracks/{track_id}/pitfalls/{pitfall_id}", response_model=TrackView)
def update_pitfall(track_id: str, pitfall_id: str, payload: PitfallUpdate) -> TrackView:
    track = _load_track_or_404(track_id)
    item = next((p for p in track.pitfalls if p.id == pitfall_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"没有找到这条避坑点：{pitfall_id}")
    if payload.text is not None:
        item.text = _pitfall_text(payload.text)
    if payload.done is not None:
        item.done = payload.done
    save_track(get_materials_root(), track)
    return _track_view(track)


@app.delete("/api/tracks/{track_id}/pitfalls/{pitfall_id}", response_model=TrackView)
def delete_pitfall(track_id: str, pitfall_id: str) -> TrackView:
    track = _load_track_or_404(track_id)
    before = len(track.pitfalls)
    track.pitfalls = [p for p in track.pitfalls if p.id != pitfall_id]
    if len(track.pitfalls) == before:
        raise HTTPException(status_code=404, detail=f"没有找到这条避坑点：{pitfall_id}")
    save_track(get_materials_root(), track)
    return _track_view(track)


# ---------- 个人调整：隐藏 / 备注 / 自己加步骤和材料（逻辑在 core/adjustments.py，MCP 共用） ----------


class HiddenUpdate(BaseModel):
    hidden: bool


class NoteUpdate(BaseModel):
    note: str | None  # null 或空字符串表示删除备注


class CustomStepCreate(BaseModel):
    title: str
    phase: str | None = None
    after: str | None = None  # 插在哪个步骤后面
    where: str | None = None


class CustomStepPatch(BaseModel):
    title: str | None = None
    where: str | None = None


class CustomMaterialCreate(BaseModel):
    name: str
    step: str
    material_type: str | None = None
    optional: bool = False


class CustomMaterialPatch(BaseModel):
    name: str | None = None
    optional: bool | None = None


def _adjust(track_id: str, action) -> TrackView:
    """个人调整的统一入口：取出办事和攻略 → 执行调整 → 保存（并维护办完日期）。"""
    track = _load_track_or_404(track_id)
    vocab, guide = _valid_guide(track.guide)
    try:
        action(guide, track, vocab)
    except AdjustmentError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _save_track(track)


@app.put("/api/tracks/{track_id}/hidden/steps/{step}", response_model=TrackView)
def hide_step(track_id: str, step: str, payload: HiddenUpdate) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.set_step_hidden(g, t, step, payload.hidden))


@app.put("/api/tracks/{track_id}/hidden/requirements/{requirement}", response_model=TrackView)
def hide_requirement(track_id: str, requirement: str, payload: HiddenUpdate) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.set_requirement_hidden(g, t, requirement, payload.hidden))


@app.put("/api/tracks/{track_id}/notes/steps/{step}", response_model=TrackView)
def note_step(track_id: str, step: str, payload: NoteUpdate) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.set_step_note(g, t, step, payload.note))


@app.put("/api/tracks/{track_id}/notes/requirements/{requirement}", response_model=TrackView)
def note_requirement(track_id: str, requirement: str, payload: NoteUpdate) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.set_requirement_note(g, t, requirement, payload.note))


@app.post("/api/tracks/{track_id}/custom-steps", response_model=TrackView)
def create_custom_step(track_id: str, payload: CustomStepCreate) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.add_custom_step(g, t, payload.title, payload.phase, payload.after, payload.where))


@app.put("/api/tracks/{track_id}/custom-steps/{step}", response_model=TrackView)
def edit_custom_step(track_id: str, step: str, payload: CustomStepPatch) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.update_custom_step(t, step, payload.title, payload.where))


@app.delete("/api/tracks/{track_id}/custom-steps/{step}", response_model=TrackView)
def remove_custom_step(track_id: str, step: str) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.delete_custom_step(t, step))


@app.post("/api/tracks/{track_id}/custom-materials", response_model=TrackView)
def create_custom_material(track_id: str, payload: CustomMaterialCreate) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.add_custom_material(g, t, v, payload.name, payload.step, payload.material_type, payload.optional))


@app.put("/api/tracks/{track_id}/custom-materials/{material}", response_model=TrackView)
def edit_custom_material(track_id: str, material: str, payload: CustomMaterialPatch) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.update_custom_material(t, material, payload.name, payload.optional))


@app.delete("/api/tracks/{track_id}/custom-materials/{material}", response_model=TrackView)
def remove_custom_material(track_id: str, material: str) -> TrackView:
    return _adjust(track_id, lambda g, t, v: adj.delete_custom_material(t, material))


class ExportRequest(BaseModel):
    # 导出到哪个文件夹，例如 "~/Desktop"；不传时用这件办事上次选的位置，再没有就用材料根目录下的 exports/
    dest: str | None = None


class ExportLocation(BaseModel):
    label: str
    path: str


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
    keep: bool | None = Form(None),
) -> TrackView:
    """在办事页面直接为一条缺失/过期的需求上传材料，并在材料凑齐时自动确认给这条需求。
    组合类型（例如护照全部页）要用 part 指明上传的是哪一部分。

    keep：要不要放进长期资料库（别的办事也能复用）。不传时按规则默认：词表认识、且不是一次性类型的
    放进长期资料库；一次性类型（行程单、解释信……）和词表不认识的，只属于这件办事。"""
    track = _load_track_or_404(track_id)
    vocab, _ = _valid_guide(track.guide)
    view = _track_view(track)
    req = next((r for r in view.requirements if r.id == requirement), None)
    if req is None:
        raise HTTPException(status_code=404, detail=f"这份攻略没有需求 {requirement}")
    if req.state == "not_applicable":
        raise HTTPException(status_code=422, detail="这条材料对你不适用，不需要上传")
    scope = None if (req.default_keep if keep is None else keep) else track.id
    if req.material_type is None:
        # 词表不认识的材料（自己加的，或攻略里的一次性材料如邀请函）：按材料名建一条"其他"类记录，
        # 默认只属于这件办事，并直接确认给这项材料——不能自动匹配，所以不依赖词表
        created = await _create_material(
            belongs_to=None, category=MaterialCategory.OTHER, type_=req.name,
            obtained_date=obtained_date or date.today(),
            sublabel=sublabel.strip() if sublabel and sublabel.strip() else None,
            validity_days=None, recommended_update_interval_days=None, recommended_update_day_of_month=None,
            file=file, for_track=scope,
        )
        track.matches[requirement] = [created.id]
        save_track(get_materials_root(), track)
        return _track_view(track)
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
        for_track=scope,
    )

    # 刚上传的是最新的一份：丢掉旧的确认，按最新候选重新判断；凑齐了就直接确认给这条需求
    track.matches.pop(requirement, None)
    refreshed = next(r for r in _track_view(track).requirements if r.id == requirement)
    if refreshed.state == "unconfirmed":
        track.matches[requirement] = [r.id for r in refreshed.records]
    save_track(get_materials_root(), track)
    return _track_view(track)


def _resolve_export_dir(text: str) -> Path:
    """校验用户给的导出位置：必须是已经存在的文件夹；不能在仓库里面（材料根目录除外），
    免得把个人材料复制进会被提交、甚至公开的目录（例如 community/）。"""
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise HTTPException(status_code=422, detail="请填完整路径，例如 ~/Desktop 或 /Users/你/Desktop")
    path = path.resolve()
    if not path.is_dir():
        raise HTTPException(status_code=422, detail=f"文件夹不存在：{path}")
    repo, materials = REPO_ROOT.resolve(), get_materials_root().resolve()
    inside_repo = path == repo or repo in path.parents
    inside_materials = path == materials or materials in path.parents
    if inside_repo and not inside_materials:
        raise HTTPException(status_code=422, detail="不能导出到项目仓库里面（会被 Git 提交），请选桌面等仓库外的位置")
    return path


@app.get("/api/export-locations", response_model=list[ExportLocation])
def export_locations() -> list[ExportLocation]:
    """导出面板上的快捷选项：只列出这台电脑上真实存在的文件夹。"""
    options = [ExportLocation(label="桌面", path="~/Desktop"), ExportLocation(label="下载", path="~/Downloads")]
    found = [o for o in options if Path(o.path).expanduser().is_dir()]
    return found + [ExportLocation(label="材料根目录", path=str(get_materials_root()))]


@app.post("/api/tracks/{track_id}/export", response_model=ExportResponse)
def export_track_materials(track_id: str, payload: ExportRequest | None = None) -> ExportResponse:
    """把已确认（状态为"已有"）的材料复制到目标文件夹下新建的 <办事标题>-<时间>/，附一份清单。"""
    track = _load_track_or_404(track_id)
    dest_text = (payload.dest.strip() if payload and payload.dest else None) or track.export_dir
    dest = _resolve_export_dir(dest_text) if dest_text else None
    view = _track_view(track)
    records = load_material_records(MATERIALS_INDEX_DIR)
    result = export_track(view, records, get_materials_root(), datetime.now(), dest_root=dest)
    if payload and payload.dest is not None:
        track.export_dir = dest_text  # 记住这次的选择，下次默认还导出到这里
        save_track(get_materials_root(), track)
    return ExportResponse(
        folder=str(result.folder), copied=result.copied,
        missing_files=result.missing_files, pending=result.pending,
    )


# 前端静态页面：web/index.html 等。放在所有 /api/... 路由之后注册，
# 这样 "/" 会命中静态文件，不会被误判成某个 API 路径。
app.mount("/", StaticFiles(directory=REPO_ROOT / "web", html=True), name="web")
