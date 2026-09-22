"""FR-003a：建议更新频率是独立于 validity_days 的另一个维度。"""

from datetime import date

from core.models import MaterialCategory, MaterialRecord
from core.update_cadence import compute_update_reminder

TODAY = date(2026, 9, 22)


def make_record(**overrides) -> MaterialRecord:
    defaults = dict(
        id="test-record",
        category=MaterialCategory.FINANCIAL_SNAPSHOT,
        type="银行流水",
        belongs_to="test-application",
    )
    defaults.update(overrides)
    return MaterialRecord(**defaults)


def test_no_interval_configured_means_not_applicable():
    record = make_record(obtained_date=date(2026, 1, 1), recommended_update_interval_days=None)
    assert compute_update_reminder(record, TODAY) is None


def test_missing_material_means_not_applicable():
    record = make_record(obtained_date=None, recommended_update_interval_days=30)
    assert compute_update_reminder(record, TODAY) is None


def test_overdue_update():
    # 2026-07-01 + 30d = 2026-07-31，早就过了今天，应该标记为 overdue。
    record = make_record(obtained_date=date(2026, 7, 1), recommended_update_interval_days=30)
    reminder = compute_update_reminder(record, TODAY)
    assert reminder is not None
    assert reminder.overdue is True
    assert reminder.days_until_due < 0


def test_upcoming_update_not_overdue():
    # 2026-09-15 + 30d = 2026-10-15，还没到，不该是 overdue。
    record = make_record(obtained_date=date(2026, 9, 15), recommended_update_interval_days=30)
    reminder = compute_update_reminder(record, TODAY)
    assert reminder is not None
    assert reminder.overdue is False
    assert reminder.days_until_due > 0


def test_day_of_month_overdue_when_payday_already_passed():
    # 上次更新 2026-08-20，发薪日是每月 15 号 —— 下一个 15 号是 2026-09-15，
    # 今天(2026-09-22)已经过了，应该是 overdue。
    record = make_record(obtained_date=date(2026, 8, 20), recommended_update_day_of_month=15)
    reminder = compute_update_reminder(record, TODAY)
    assert reminder is not None
    assert reminder.due_date == date(2026, 9, 15)
    assert reminder.overdue is True


def test_day_of_month_not_overdue_when_payday_upcoming():
    # 上次更新就是发薪日当天 2026-09-15，下一个 15 号是 2026-10-15，还没到。
    record = make_record(obtained_date=date(2026, 9, 15), recommended_update_day_of_month=15)
    reminder = compute_update_reminder(record, TODAY)
    assert reminder is not None
    assert reminder.due_date == date(2026, 10, 15)
    assert reminder.overdue is False


def test_day_of_month_clamped_when_day_does_not_exist_in_month():
    # 上次更新 2026-01-31，设成"每月 31 号"，2 月没有 31 号，应该退到 2 月的最后一天。
    record = make_record(obtained_date=date(2026, 1, 31), recommended_update_day_of_month=31)
    reminder = compute_update_reminder(record, date(2026, 2, 1))
    assert reminder is not None
    assert reminder.due_date == date(2026, 2, 28)  # 2026 不是闰年


def test_day_of_month_takes_priority_over_interval_when_both_set():
    record = make_record(
        obtained_date=date(2026, 8, 20),
        recommended_update_interval_days=9999,  # 故意设一个很离谱的值，确认没被用到
        recommended_update_day_of_month=15,
    )
    reminder = compute_update_reminder(record, TODAY)
    assert reminder is not None
    assert reminder.due_date == date(2026, 9, 15)
