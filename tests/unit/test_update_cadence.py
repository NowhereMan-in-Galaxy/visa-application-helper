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
