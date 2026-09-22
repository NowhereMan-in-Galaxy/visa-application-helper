"""对应 spec.md User Story 1 的 Acceptance Scenario 2：状态由 obtained_date + validity_days +
今天的日期机械算出来，不需要人工判断——这里把"今天"固定死，保证测试结果永远一样。
"""

from datetime import date

from core.models import MaterialCategory, MaterialRecord, MaterialStatus
from core.status import compute_status

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


def test_missing_obtained_date_means_needs_material():
    record = make_record(obtained_date=None)
    result = compute_status(record, TODAY)
    assert result.status == MaterialStatus.NEEDS_MATERIAL
    assert result.days_until_expiry is None


def test_no_validity_rule_means_complete_forever():
    record = make_record(obtained_date=date(2020, 1, 1), validity_days=None)
    result = compute_status(record, TODAY)
    assert result.status == MaterialStatus.COMPLETE
    assert result.days_until_expiry is None


def test_well_within_validity_window_is_complete():
    record = make_record(obtained_date=date(2026, 9, 1), validity_days=90)
    result = compute_status(record, TODAY)
    assert result.status == MaterialStatus.COMPLETE
    assert result.days_until_expiry == 69  # 2026-09-01 + 90d = 2026-11-30


def test_within_warning_window_is_expiring_soon():
    # 2026-07-01 + 90d = 2026-09-29，距今天 7 天，落在 14 天提醒窗口内。
    record = make_record(obtained_date=date(2026, 7, 1), validity_days=90)
    result = compute_status(record, TODAY)
    assert result.status == MaterialStatus.EXPIRING_SOON
    assert result.days_until_expiry == 7


def test_past_validity_window_is_expired():
    # 2026-08-15 + 30d = 2026-09-14，已经过了今天。
    record = make_record(obtained_date=date(2026, 8, 15), validity_days=30)
    result = compute_status(record, TODAY)
    assert result.status == MaterialStatus.EXPIRED
    assert result.days_until_expiry == -8
