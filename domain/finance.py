from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.fields import require_text
from domain.numbers import round_money

INSTALLMENT_INTERVAL_DAYS = 30


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


class EntryStatus(StrEnum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class EntryDisplayStatus(StrEnum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


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


@dataclass(frozen=True, slots=True)
class Installment:
    number: int
    count: int
    amount: Decimal
    due_date: date


def split_installments(total: Decimal, count: int, start_date: date, first_due_days: int) -> list[Installment]:
    if count < 1:
        raise BusinessRuleError("O número de parcelas deve ser pelo menos 1.")
    base = round_money(total / count)
    amounts = [base] * (count - 1) + [total - base * (count - 1)]
    return [
        Installment(
            number=index + 1,
            count=count,
            amount=amount,
            due_date=start_date + timedelta(days=first_due_days + INSTALLMENT_INTERVAL_DAYS * index),
        )
        for index, amount in enumerate(amounts)
    ]


def display_status(status: EntryStatus, due_date: date, today: date) -> EntryDisplayStatus:
    if status is EntryStatus.PENDING and due_date < today:
        return EntryDisplayStatus.OVERDUE
    return EntryDisplayStatus(status.value)
