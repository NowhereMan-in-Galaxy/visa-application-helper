"""对应 specs/001-visa-material-hub/spec.md 的 Key Entities（本轮只实现 User Story 1 用到的两个）。

有效期（validity）和更新提醒（recommended update）都用整数天数表示，不用"几个月"这种日历单位——
天数加减法没有歧义（每个月天数不一样，"3 个月后"这种说法本身就模糊），FR-003a 已经把这两个字段
明确成两个独立维度，这里用统一的天数单位实现，避免引入不必要的日历计算复杂度。
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class MaterialCategory(str, Enum):
    """spec.md FR-001 锁定的五大类。"""

    PERSONAL_INFO = "personal_info"
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
    belongs_to: str  # 所属 VisaApplication 的 id

    # obtained_date 为空表示"这条材料还没拿到手，只是先占个位置"，对应状态"待补"。
    obtained_date: date | None = None

    # 有效期规则：材料从 obtained_date 起多少天内视为有效；留空表示这类材料没有过期概念
    # （例如证件照通常不强制过期，只是建议更新）。
    validity_days: int | None = None

    # 建议更新频率：与 validity_days 是两个独立维度（FR-003a），例如财务快照即使没过期，
    # 也可能因为太久没同步新的一份而需要提醒。留空表示这类材料不需要主动提醒更新。
    recommended_update_interval_days: int | None = None

    # 相对于"材料根目录"（见 src/config.py）的相对路径，不存文件内容本身。
    file_ref: str | None = None

    sublabel: str | None = None
