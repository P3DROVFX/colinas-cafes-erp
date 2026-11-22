from datetime import date
from decimal import Decimal

import pytest

from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.finance import AccountKind, DreGroup, EntryType, FinancialAccountInput, FinancialCategoryInput
from services import finance_setup as finance_setup_service


def find_by_name(rows: list[dict], name: str) -> dict:
    return next(row for row in rows if row["name"] == name)


def test_system_category_is_locked(make_user):
    finance = make_user(Role.FINANCE)
    category = find_by_name(finance_setup_service.list_financial_categories(finance), "Venda de cafés")
    renamed = FinancialCategoryInput("Vendas", EntryType.RECEIVABLE, DreGroup.REVENUE)
    with pytest.raises(BusinessRuleError):
        finance_setup_service.update_financial_category(finance, category["id"], renamed)
    with pytest.raises(BusinessRuleError):
        finance_setup_service.delete_financial_category(finance, category["id"])
    with pytest.raises(BusinessRuleError):
        finance_setup_service.set_financial_category_active(finance, category["id"], False)


def test_custom_category_lifecycle(make_user):
    finance = make_user(Role.FINANCE)
    data = FinancialCategoryInput("Cursos e eventos", EntryType.PAYABLE, DreGroup.OPERATING_EXPENSE)
    category_id = finance_setup_service.create_financial_category(finance, data)
    finance_setup_service.set_financial_category_active(finance, category_id, False)
    finance_setup_service.delete_financial_category(finance, category_id)
    assert "Cursos e eventos" not in [
        row["name"] for row in finance_setup_service.list_financial_categories(finance, include_inactive=True)
    ]


def test_system_account_keeps_kind_but_can_be_renamed(make_user):
    manager = make_user(Role.MANAGER)
    account = find_by_name(finance_setup_service.list_financial_accounts(manager), "Banco - conta PJ")
    renamed = FinancialAccountInput("Banco do Nordeste - PJ", AccountKind.BANK, Decimal("1500"), date(2026, 6, 1))
    finance_setup_service.update_financial_account(manager, account["id"], renamed)
    with pytest.raises(BusinessRuleError):
        finance_setup_service.update_financial_account(
            manager, account["id"], FinancialAccountInput("Banco", AccountKind.CASH, Decimal("0"), date(2026, 6, 1))
        )


def test_production_cannot_see_finance_setup(make_user):
    with pytest.raises(AccessDeniedError):
        finance_setup_service.list_financial_categories(make_user(Role.PRODUCTION))
