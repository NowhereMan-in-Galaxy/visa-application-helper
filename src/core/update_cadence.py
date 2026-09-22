""""建议更新频率"的提醒计算（spec.md FR-003a、FR-014）。

跟 status.py 判断的"过没过期"是两件独立的事：一份银行流水可能还在有效期内，
但如果你习惯每月更新一次、已经两个月没传新的了，这里也应该提醒你。

两种互斥的周期表达（FR-014）：
- recommended_update_interval_days：滚动周期，"上次更新后 N 天"
- recommended_update_day_of_month：日历周期，"每月固定第几天"（例如发薪日）——
  用滚动天数模拟"每月"会随着大小月慢慢跑偏，日历周期没有这个问题。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from core.models import MaterialRecord


@dataclass(frozen=True)
class UpdateReminder:
    due_date: date
    days_until_due: int
    overdue: bool


def _clamp_day_to_month(year: int, month: int, day: int) -> date:
    """day_of_month 在某些月份可能不存在（比如设成 31 号，遇到 2 月），退到当月最后一天。"""
    last_day_of_month = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day_of_month))


def _first_of_next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _next_occurrence_of_day_of_month(after: date, day_of_month: int) -> date:
    """返回严格晚于 `after` 的、下一个"这个月第 day_of_month 天"是哪天。"""
    candidate = _clamp_day_to_month(after.year, after.month, day_of_month)
    if candidate > after:
        return candidate
    next_year, next_month = _first_of_next_month(after.year, after.month)
    return _clamp_day_to_month(next_year, next_month, day_of_month)


def compute_update_reminder(record: MaterialRecord, today: date) -> UpdateReminder | None:
    """材料还没拿到手（obtained_date 为空），或者两种周期都没配置，这个提醒不适用，返回 None。"""
    if record.obtained_date is None:
        return None

    if record.recommended_update_day_of_month is not None:
        due_date = _next_occurrence_of_day_of_month(
            record.obtained_date, record.recommended_update_day_of_month
        )
    elif record.recommended_update_interval_days is not None:
        due_date = record.obtained_date + timedelta(days=record.recommended_update_interval_days)
    else:
        return None

    days_until_due = (due_date - today).days
    return UpdateReminder(
        due_date=due_date,
        days_until_due=days_until_due,
        overdue=days_until_due < 0,
    )
