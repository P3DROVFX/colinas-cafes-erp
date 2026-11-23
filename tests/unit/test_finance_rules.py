from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.finance import (
    AccountKind,
    DreGroup,
    EntryDisplayStatus,
    EntryStatus,
    EntryType,
    FinancialAccountInput,
    FinancialCategoryInput,
    display_status,
    dre_groups_for,
    split_installments,
    validate_financial_account,
    validate_financial_category,
)


def test_dre_groups_are_split_by_entry_type():
    assert dre_groups_for(EntryType.RECEIVABLE) == [DreGroup.REVENUE, DreGroup.OTHER_REVENUE]
    assert DreGroup.OPERATING_EXPENSE in dre_groups_for(EntryType.PAYABLE)


def test_category_group_must_match_entry_type():
    with pytest.raises(BusinessRuleError):
        validate_financial_category(FinancialCategoryInput("Frete", EntryType.RECEIVABLE, DreGroup.SELLING_COST))


def test_account_opening_date_cannot_be_in_the_future():
    today = date(2026, 11, 22)
    account = FinancialAccountInput("Banco", AccountKind.BANK, Decimal("100"), today + timedelta(days=1))
    with pytest.raises(BusinessRuleError):
        validate_financial_account(account, today)


def test_installments_split_total_and_space_due_dates():
    installments = split_installments(Decimal("1800.00"), 2, date(2026, 11, 22), 30)
    assert [item.amount for item in installments] == [Decimal("900.00"), Decimal("900.00")]
    assert [item.due_date for item in installments] == [date(2026, 12, 22), date(2027, 1, 21)]


def test_installment_rounding_remainder_stays_on_last():
    amounts = [item.amount for item in split_installments(Decimal("100.00"), 3, date(2026, 11, 22), 0)]
    assert amounts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


def test_pending_entry_past_due_is_overdue():
    assert display_status(EntryStatus.PENDING, date(2026, 11, 21), date(2026, 11, 22)) is EntryDisplayStatus.OVERDUE
    assert display_status(EntryStatus.SETTLED, date(2026, 11, 21), date(2026, 11, 22)) is EntryDisplayStatus.SETTLED
