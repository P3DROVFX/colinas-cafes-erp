from datetime import date
from typing import Any

from core.db import transaction
from core.errors import BusinessRuleError
from domain.access import Permission, User, ensure_permission
from domain.finance import (
    FinancialAccountInput,
    FinancialCategoryInput,
    validate_financial_account,
    validate_financial_category,
)
from repositories import finance_setup as finance_setup_repository
from repositories import records
from repositories.records import MasterTable
from services.master_data import (
    delete_master_record,
    duplicate_guard,
    ensure_unchanged,
    load_record,
    record_values,
    set_master_record_active,
)

DUPLICATE_CATEGORY_MESSAGE = "Já existe uma categoria com este nome."
DUPLICATE_ACCOUNT_MESSAGE = "Já existe uma conta com este nome."


def list_financial_categories(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_FINANCE_SETUP)
    with transaction(actor.email) as connection:
        return finance_setup_repository.list_financial_categories(connection, search, include_inactive)


def create_financial_category(actor: User, data: FinancialCategoryInput) -> int:
    ensure_permission(actor, Permission.MANAGE_FINANCE_SETUP)
    data = validate_financial_category(data)
    with duplicate_guard(DUPLICATE_CATEGORY_MESSAGE), transaction(actor.email) as connection:
        return records.insert_record(connection, MasterTable.FINANCIAL_CATEGORIES, record_values(data))


def update_financial_category(actor: User, category_id: int, data: FinancialCategoryInput) -> None:
    ensure_permission(actor, Permission.MANAGE_FINANCE_SETUP)
    data = validate_financial_category(data)
    with duplicate_guard(DUPLICATE_CATEGORY_MESSAGE), transaction(actor.email) as connection:
        category = load_record(connection, MasterTable.FINANCIAL_CATEGORIES, category_id)
        if category["is_system"]:
            raise BusinessRuleError("Categorias do sistema são usadas pelas integrações e não podem ser alteradas.")
        records.update_record(connection, MasterTable.FINANCIAL_CATEGORIES, category_id, record_values(data))


def delete_financial_category(actor: User, category_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_FINANCE_SETUP,
        MasterTable.FINANCIAL_CATEGORIES,
        category_id,
        "Esta categoria já classifica lançamentos. Inative-a para tirá-la dos novos lançamentos.",
    )


def set_financial_category_active(actor: User, category_id: int, is_active: bool) -> None:
    set_master_record_active(
        actor, Permission.MANAGE_FINANCE_SETUP, MasterTable.FINANCIAL_CATEGORIES, category_id, is_active
    )


def list_financial_accounts(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_FINANCE_SETUP)
    with transaction(actor.email) as connection:
        return finance_setup_repository.list_financial_accounts(connection, search, include_inactive)


def create_financial_account(actor: User, data: FinancialAccountInput) -> int:
    ensure_permission(actor, Permission.MANAGE_FINANCE_SETUP)
    data = validate_financial_account(data, date.today())
    with duplicate_guard(DUPLICATE_ACCOUNT_MESSAGE), transaction(actor.email) as connection:
        return records.insert_record(connection, MasterTable.FINANCIAL_ACCOUNTS, record_values(data))


def update_financial_account(actor: User, account_id: int, data: FinancialAccountInput) -> None:
    ensure_permission(actor, Permission.MANAGE_FINANCE_SETUP)
    data = validate_financial_account(data, date.today())
    values = record_values(data)
    with duplicate_guard(DUPLICATE_ACCOUNT_MESSAGE), transaction(actor.email) as connection:
        account = load_record(connection, MasterTable.FINANCIAL_ACCOUNTS, account_id)
        if account["is_system"]:
            ensure_unchanged(
                account,
                values,
                ("kind",),
                "O tipo das contas do sistema não pode mudar, porque as integrações dependem dele.",
            )
        records.update_record(connection, MasterTable.FINANCIAL_ACCOUNTS, account_id, values)


def delete_financial_account(actor: User, account_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_FINANCE_SETUP,
        MasterTable.FINANCIAL_ACCOUNTS,
        account_id,
        "Esta conta já tem lançamentos liquidados. Inative-a para tirá-la das novas liquidações.",
    )


def set_financial_account_active(actor: User, account_id: int, is_active: bool) -> None:
    set_master_record_active(
        actor, Permission.MANAGE_FINANCE_SETUP, MasterTable.FINANCIAL_ACCOUNTS, account_id, is_active
    )
