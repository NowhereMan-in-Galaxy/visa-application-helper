"""材料状态的确定性判断（docs/SPEC-mvp.md 第 2 条"核心库"——不调用模型，相同输入永远得到相同输出）。

`today` 作为参数传入，而不是在函数内部调用 `date.today()`：这样测试时可以传一个固定日期，
不用等真实日期变化、也不用 mock 系统时钟，结果永远可复现（见 tests/unit/test_status.py）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from core.models import MaterialRecord, MaterialStatus

# 材料到期前多少天开始提醒"即将过期"，而不是等到过期当天才提醒。
EXPIRING_SOON_WINDOW_DAYS = 14


@dataclass(frozen=True)
class StatusResult:
    status: MaterialStatus
    # 材料还剩多少天过期；没有 validity_days（不存在过期概念）或者材料还没拿到手时为 None。
    days_until_expiry: int | None


def compute_status(record: MaterialRecord, today: date) -> StatusResult:
    if record.obtained_date is None:
        return StatusResult(status=MaterialStatus.NEEDS_MATERIAL, days_until_expiry=None)

    if record.validity_days is None:
        return StatusResult(status=MaterialStatus.COMPLETE, days_until_expiry=None)

    expiry_date = record.obtained_date + timedelta(days=record.validity_days)
    days_left = (expiry_date - today).days

    if days_left < 0:
        return StatusResult(status=MaterialStatus.EXPIRED, days_until_expiry=days_left)
    if days_left <= EXPIRING_SOON_WINDOW_DAYS:
        return StatusResult(status=MaterialStatus.EXPIRING_SOON, days_until_expiry=days_left)
    return StatusResult(status=MaterialStatus.COMPLETE, days_until_expiry=days_left)
