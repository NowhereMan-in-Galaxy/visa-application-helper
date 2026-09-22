"""对应 specs/001-visa-material-hub/spec.md 的 Key Entities。

有效期（validity）和更新提醒（recommended update）都用整数天数表示，不用"几个月"这种日历单位——
天数加减法没有歧义（每个月天数不一样，"3 个月后"这种说法本身就模糊），FR-003a 已经把这两个字段
明确成两个独立维度，这里用统一的天数单位实现，避免引入不必要的日历计算复杂度。
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class MaterialCategory(str, Enum):
    """spec.md FR-001 锁定的四大类（结构化个人信息不算在内，走 PersonalProfile，见 FR-011）。"""

    PASSPORT_SCAN = "passport_scan"
    FINANCIAL_SNAPSHOT = "financial_snapshot"
    EMPLOYMENT_DOC = "employment_doc"
    ID_PHOTO = "id_photo"


class MaterialStatus(str, Enum):
    """spec.md 锁定的四种状态（对应 docs/SPEC-mvp.md 第 4/5 条）。"""

    NEEDS_MATERIAL = "待补"
    COMPLETE = "已备齐"
    EXPIRING_SOON = "即将过期"
    EXPIRED = "已过期"


class VisaApplication(BaseModel):
    """一次具体的签证申请（spec.md Key Entities）。"""

    id: str
    country: str
    visa_type: str
    deadline: date  # DDL：整次申请统一的提交截止日期（FR-004、FR-006）


class MaterialRecord(BaseModel):
    """一条材料记录，对应 docs/SPEC-mvp.md 第 4 条锁定字段的扩展版本（spec.md FR-001）。"""

    id: str
    category: MaterialCategory
    type: str  # 人类可读的材料类型名称，例如"银行流水"

    # 所属 VisaApplication 的 id；留空表示这条材料属于个人材料库，不挂靠任何具体申请
    # （例如证件类——护照、身份证、户口本——是长期积累的个人资产，不是为某一次申请单独
    # 准备的，参考 PersonalProfile 已经确立的"申请人级别、不挂 belongs_to"模式）。
    # financial_snapshot / employment_doc 这两类目前实践上仍然会填具体申请 id，
    # 但字段本身不强制——要不要让它们也支持"不挂靠"，留给以后再评估。
    belongs_to: str | None = None

    # obtained_date 为空表示"这条材料还没拿到手，只是先占个位置"，对应状态"待补"。
    obtained_date: date | None = None

    # 有效期规则：材料从 obtained_date 起多少天内视为有效；留空表示这类材料没有过期概念
    # （例如证件照通常不强制过期，只是建议更新）。
    validity_days: int | None = None

    # 建议更新频率：与 validity_days 是两个独立维度（FR-003a），例如财务快照即使没过期，
    # 也可能因为太久没同步新的一份而需要提醒。这里有两种互斥的表达方式（FR-014），一条记录
    # 只能用其中一种：
    #   - recommended_update_interval_days：滚动周期，"每隔 N 天"（例如证件照每 180 天）
    #   - recommended_update_day_of_month：日历周期，"每月固定第几天"（例如发薪日是 15 号，
    #     工资流水按这个提醒比"上次更新后 N 天"更准，因为每个月天数不一样，滚动周期会慢慢偏移）
    # 两个都留空表示这类材料不需要主动提醒更新。
    recommended_update_interval_days: int | None = None
    recommended_update_day_of_month: int | None = None

    # 相对于"材料根目录"（见 src/config.py）的相对路径，不存文件内容本身。
    file_ref: str | None = None

    sublabel: str | None = None


class TravelHistoryEntry(BaseModel):
    """PersonalProfile.travel_history 里的一条出行记录（spec.md Key Entities）。

    country 可以留空：从出入境记录能推出"这段时间出境了"，但推不出具体去了哪个国家时
    （比如只有出发口岸、没有目的地信息），应该让用户自己补，而不是猜一个可能错的国家。
    """

    country: str | None = None
    entry_date: date
    exit_date: date | None = None  # 还在境外、尚未返回时留空
    purpose: str | None = None


class PersonalProfile(BaseModel):
    """申请人级别的结构化个人信息，不挂在某次具体签证申请下（spec.md FR-011）。

    这份数据本身就是"真实个人信息"，实际内容 MUST NOT 出现在 materials_index/（仓库会追踪
    的部分）——存储位置见 src/core/profile_storage.py 的说明。
    """

    full_name: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    passport_number: str | None = None
    travel_history: list[TravelHistoryEntry] = []
