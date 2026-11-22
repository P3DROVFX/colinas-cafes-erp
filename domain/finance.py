from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.fields import require_text


class EntryType(StrEnum):
    PAYABLE = "PAYABLE"
    RECEIVABLE = "RECEIVABLE"


class DreGroup(StrEnum):
    REVENUE = "REVENUE"
    OTHER_REVENUE = "OTHER_REVENUE"
    REFUND = "REFUND"
    INVENTORY = "INVENTORY"
    SELLING_COST = "SELLING_COST"
    OPERATING_EXPENSE = "OPERATING_EXPENSE"


class AccountKind(StrEnum):
    CASH = "CASH"
    BANK = "BANK"


DRE_GROUP_ENTRY_TYPES: dict[DreGroup, EntryType] = {
    DreGroup.REVENUE: EntryType.RECEIVABLE,
    DreGroup.OTHER_REVENUE: EntryType.RECEIVABLE,
    DreGroup.REFUND: EntryType.PAYABLE,
    DreGroup.INVENTORY: EntryType.PAYABLE,
    DreGroup.SELLING_COST: EntryType.PAYABLE,
    DreGroup.OPERATING_EXPENSE: EntryType.PAYABLE,
}


@dataclass(frozen=True, slots=True)
class FinancialCategoryInput:
    name: str
    entry_type: EntryType
    dre_group: DreGroup


@dataclass(frozen=True, slots=True)
class FinancialAccountInput:
    name: str
    kind: AccountKind
    opening_balance: Decimal
    opening_date: date


def dre_groups_for(entry_type: EntryType) -> list[DreGroup]:
    return [group for group, group_type in DRE_GROUP_ENTRY_TYPES.items() if group_type is entry_type]


def validate_financial_category(data: FinancialCategoryInput) -> FinancialCategoryInput:
    if DRE_GROUP_ENTRY_TYPES[data.dre_group] is not data.entry_type:
        raise BusinessRuleError("O grupo da DRE não combina com o tipo da categoria (a pagar ou a receber).")
    return replace(data, name=require_text(data.name, "Informe o nome da categoria."))


def validate_financial_account(data: FinancialAccountInput, today: date) -> FinancialAccountInput:
    if data.opening_date > today:
        raise BusinessRuleError("A data do saldo inicial não pode estar no futuro.")
    return replace(data, name=require_text(data.name, "Informe o nome da conta."))
