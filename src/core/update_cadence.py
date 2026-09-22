""""建议更新频率"的提醒计算（spec.md FR-003a）。

跟 status.py 判断的"过没过期"是两件独立的事：一份银行流水可能还在有效期内，
但如果你习惯每月更新一次、已经两个月没传新的了，这里也应该提醒你。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from core.models import MaterialRecord


@dataclass(frozen=True)
class UpdateReminder:
    due_date: date
    days_until_due: int
    overdue: bool


def compute_update_reminder(record: MaterialRecord, today: date) -> UpdateReminder | None:
    """材料没有 recommended_update_interval_days，或者还没拿到手（obtained_date 为空）时，
    这个提醒不适用，返回 None。"""
    if record.obtained_date is None or record.recommended_update_interval_days is None:
        return None

    due_date = record.obtained_date + timedelta(days=record.recommended_update_interval_days)
    days_until_due = (due_date - today).days
    return UpdateReminder(
        due_date=due_date,
        days_until_due=days_until_due,
        overdue=days_until_due < 0,
    )
