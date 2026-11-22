from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.finance import (
    AccountKind,
    DreGroup,
    EntryType,
    FinancialAccountInput,
    FinancialCategoryInput,
    dre_groups_for,
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
