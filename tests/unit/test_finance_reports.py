from datetime import date
from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.finance import (
    CashMovement,
    DreGroup,
    EntryStatus,
    EntryType,
    Granularity,
    IncomeStatement,
    ManualEntryInput,
    balance_series,
    build_cash_flow,
    build_forecast,
    ensure_settlement_date,
    ensure_settlement_reversible,
    period_start,
    schedule_entries,
    validate_manual_entry,
)
from domain.settings import SettingType, ensure_consistent_settings, normalize_setting

TODAY = date(2026, 11, 23)


def movement(day: int, entry_type: EntryType, amount: str) -> CashMovement:
    return CashMovement(date(2026, 11, day), 1, entry_type, Decimal(amount))


def test_demo_cash_flow_day():
    movements = [
        movement(23, EntryType.RECEIVABLE, "49.90"),
        movement(23, EntryType.RECEIVABLE, "127.80"),
        movement(23, EntryType.PAYABLE, "4.47"),
        movement(23, EntryType.PAYABLE, "900"),
    ]
    [period] = build_cash_flow(movements, Decimal("0"), Granularity.DAY)
    assert (period.inflow, period.outflow, period.net, period.balance) == (
        Decimal("177.70"),
        Decimal("904.47"),
        Decimal("-726.77"),
        Decimal("-726.77"),
    )


def test_cash_flow_groups_by_week_and_accumulates():
    movements = [movement(16, EntryType.RECEIVABLE, "100"), movement(18, EntryType.PAYABLE, "30"),
                 movement(23, EntryType.RECEIVABLE, "50")]  # fmt: skip
    periods = build_cash_flow(movements, Decimal("1000"), Granularity.WEEK)
    assert [(period.start, period.balance) for period in periods] == [
        (date(2026, 11, 16), Decimal("1070")),
        (date(2026, 11, 23), Decimal("1120")),
    ]


@pytest.mark.parametrize(
    ("granularity", "expected"),
    [
        (Granularity.DAY, date(2026, 11, 25)),
        (Granularity.WEEK, date(2026, 11, 23)),
        (Granularity.MONTH, date(2026, 11, 1)),
    ],
)
def test_period_start(granularity, expected):
    assert period_start(date(2026, 11, 25), granularity) == expected


def test_forecast_counts_overdue_entries_now():
    pending = [
        (date(2026, 11, 1), EntryType.PAYABLE, Decimal("100")),
        (date(2026, 12, 21), EntryType.PAYABLE, Decimal("375")),
        (date(2027, 1, 22), EntryType.RECEIVABLE, Decimal("900")),
    ]
    buckets = build_forecast(pending, Decimal("500"), TODAY)
    assert [(bucket.inflow, bucket.outflow, bucket.projected_balance) for bucket in buckets] == [
        (Decimal("0"), Decimal("475"), Decimal("25")),
        (Decimal("900"), Decimal("475"), Decimal("925")),
        (Decimal("900"), Decimal("475"), Decimal("925")),
    ]


def test_manual_entry_rules_and_recurrence():
    data = ManualEntryInput(1, " Aluguel ", Decimal("1200"), date(2027, 1, 31), repeat_months=3)
    data = validate_manual_entry(data, DreGroup.OPERATING_EXPENSE, TODAY)
    schedule = schedule_entries(data, TODAY)
    assert [(item.description, item.due_date) for item in schedule] == [
        ("Aluguel (1/3)", date(2027, 1, 31)),
        ("Aluguel (2/3)", date(2027, 2, 28)),
        ("Aluguel (3/3)", date(2027, 3, 31)),
    ]
    with pytest.raises(BusinessRuleError, match="despesa operacional"):
        validate_manual_entry(data, DreGroup.INVENTORY, TODAY)
    with pytest.raises(BusinessRuleError, match="maior que zero"):
        validate_manual_entry(ManualEntryInput(1, "x", Decimal("0"), TODAY), DreGroup.OPERATING_EXPENSE, TODAY)


def test_settlement_rules():
    ensure_settlement_date(EntryStatus.PENDING, TODAY, TODAY, TODAY)
    with pytest.raises(BusinessRuleError, match="pendentes"):
        ensure_settlement_date(EntryStatus.SETTLED, TODAY, TODAY, TODAY)
    with pytest.raises(BusinessRuleError, match="futuro"):
        ensure_settlement_date(EntryStatus.PENDING, TODAY, date(2026, 11, 24), TODAY)
    with pytest.raises(BusinessRuleError, match="conciliado"):
        ensure_settlement_reversible(EntryStatus.SETTLED, True)
    ensure_settlement_reversible(EntryStatus.SETTLED, False)


def test_income_statement_lines():
    month = IncomeStatement(TODAY, Decimal("159.70"), Decimal("18"), Decimal("0"), Decimal("60.02"),
                            Decimal("29.67"), Decimal("-20.01"), Decimal("180"))  # fmt: skip
    assert (month.total_revenue, month.gross_profit, month.result) == (
        Decimal("177.70"),
        Decimal("117.68"),
        Decimal("-112.00"),
    )
    assert month.gross_margin_pct == Decimal("62.4")


@pytest.mark.parametrize(
    ("key", "value_type", "raw", "expected"),
    [
        ("max_discount_pct", SettingType.DECIMAL, "12,50", "12.5"),
        ("max_discount_pct", SettingType.DECIMAL, "10.00", "10"),
        ("quote_validity_days", SettingType.INT, "7", "7"),
        ("default_shipping_box_id", SettingType.INT, "", None),
        ("operation_start_date", SettingType.DATE, "2026-06-01", "2026-06-01"),
    ],
)
def test_settings_are_normalized(key, value_type, raw, expected):
    assert normalize_setting(key, value_type, raw, "Parâmetro") == expected


def test_settings_consistency():
    ensure_consistent_settings({"roast_min_kg": "1", "roaster_capacity_kg": "15"})
    with pytest.raises(BusinessRuleError, match="capacidade"):
        ensure_consistent_settings({"roast_min_kg": "20", "roaster_capacity_kg": "15"})


def test_balance_series_carries_balance_forward():
    periods = build_cash_flow([movement(20, EntryType.PAYABLE, "100")], Decimal("50"), Granularity.DAY)
    series = balance_series(periods, Decimal("50"), date(2026, 11, 19), date(2026, 11, 21), Granularity.DAY)
    assert series == [(date(2026, 11, 19), Decimal("50")), (date(2026, 11, 20), Decimal("-50")),
                      (date(2026, 11, 21), Decimal("-50"))]  # fmt: skip
