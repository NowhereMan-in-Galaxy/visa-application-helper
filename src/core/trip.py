"""这次行程的信息（specs/007-trip-info）：每件办事自己的一份，存在 Track 的 trip 里，不写进基本信息。

字段写法和「基本信息」一样用 models._f（中文标签、下拉选项），界面和填表引擎都能复用同一套描述。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Literal

from core.models import Address, _describe_model, _f, _ProfilePart
from core.profile_storage import _merge

PAYER_OPTIONS = {"self": "自己", "host": "邀请方", "employer": "单位", "family": "家人", "other": "其他"}


class Companion(_ProfilePart):
    name: str | None = _f("姓名")
    relationship: str | None = _f("关系")


class ItineraryLeg(_ProfilePart):
    start_date: date | None = _f("开始")
    end_date: date | None = _f("结束")
    city: str | None = _f("城市")
    plan: str | None = _f("安排")


class TripInfo(_ProfilePart):
    # purpose 目的
    purpose: str | None = _f("目的")
    purpose_detail: str | None = _f("具体做什么", widget="textarea")
    # dates 日期
    arrival_date: date | None = _f("计划入境日期")
    departure_date: date | None = _f("计划离境日期")
    arrival_city: str | None = _f("入境城市")
    # transport 交通
    arrival_flight: str | None = _f("去程航班 / 车次")
    departure_flight: str | None = _f("返程航班 / 车次")
    # itinerary 行程安排（旅游签证的行程单、商务签证的日程）
    itinerary: list[ItineraryLeg] = _f("行程安排", default=[])
    # stay 住处
    stay_name: str | None = _f("酒店 / 住处名称")
    stay_address: Address = _f("住处地址", default=Address)
    stay_phone: str | None = _f("住处电话")
    # host 邀请人 / 联系人
    host_organization: str | None = _f("单位 / 机构")
    host_name: str | None = _f("联系人姓名")
    host_relationship: str | None = _f("和你的关系")
    host_address: Address = _f("地址", default=Address)
    host_phone: str | None = _f("电话")
    host_email: str | None = _f("邮箱")
    # funding 费用
    payer: Literal["self", "host", "employer", "family", "other"] | None = _f("谁出钱", options=PAYER_OPTIONS)
    payer_detail: str | None = _f("说明（例如出钱的人是谁）")
    # companions 同行人
    companions: list[Companion] = _f("同行人", default=[])


# 攻略里用的组名 → (中文名, 字段)；顺序是默认显示顺序
TRIP_GROUPS: dict[str, tuple[str, list[str]]] = {
    "purpose": ("目的", ["purpose", "purpose_detail"]),
    "dates": ("日期", ["arrival_date", "departure_date", "arrival_city"]),
    "transport": ("交通", ["arrival_flight", "departure_flight"]),
    "itinerary": ("行程安排", ["itinerary"]),
    "stay": ("住处", ["stay_name", "stay_address", "stay_phone"]),
    "host": ("邀请人 / 联系人", ["host_organization", "host_name", "host_relationship", "host_address", "host_phone", "host_email"]),
    "funding": ("费用", ["payer", "payer_detail"]),
    "companions": ("同行人", ["companions"]),
}


def trip_group_keys(category: str, declared: list[str] | None) -> list[str]:
    """这件办事要问哪几组：攻略写了 trip 就按它；没写时签证类问全部，其他不问。"""
    if declared is not None:
        return list(declared)
    return list(TRIP_GROUPS) if category == "签证" else []


def describe_trip_groups(keys: list[str]) -> list[dict[str, Any]]:
    fields = {f["key"]: f for f in _describe_model(TripInfo)}
    return [{"key": k, "label": TRIP_GROUPS[k][0], "fields": [fields[n] for n in TRIP_GROUPS[k][1]]} for k in keys]


def merge_trip(current: TripInfo, changes: dict) -> TripInfo:
    """只改提到的字段：对象逐键合并，列表整体替换。字段名不对、值不合法抛 pydantic ValidationError。"""
    return TripInfo.model_validate(_merge(current.model_dump(mode="json"), changes))


# 「让 Agent 整理」能读的文件（spec 007 第 2 步）
READABLE_SUFFIXES = (".pdf", ".txt", ".md", ".docx", ".png", ".jpg", ".jpeg", ".webp")


def trip_materials(track: Any, records: list, one_off: Callable[[Any], bool]) -> list[dict[str, Any]]:
    """这件事的材料：确认挂在这件事上的，或者只属于这件事的（for_track）；只列能读的格式。不碰文件系统。

    one_off(record) 判断是不是一次性材料（默认勾上）。返回 [{id, type, sublabel, one_off}]，不含路径。
    """
    matched = {i for ids in track.matches.values() for i in ids}
    out = []
    for r in records:
        if not (r.id in matched or r.for_track == track.id):
            continue
        if not r.file_ref or not r.file_ref.lower().endswith(READABLE_SUFFIXES):
            continue
        out.append({"id": r.id, "type": r.type, "sublabel": r.sublabel,
                    "one_off": r.for_track == track.id or one_off(r)})
    return out
