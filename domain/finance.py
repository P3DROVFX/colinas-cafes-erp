from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.dates import add_months
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


MANUAL_ENTRY_GROUPS = frozenset({DreGroup.OPERATING_EXPENSE, DreGroup.OTHER_REVENUE})
CASH_ONLY_GROUPS = frozenset({DreGroup.REFUND, DreGroup.INVENTORY})
MAX_RECURRENCE_MONTHS = 12
FORECAST_HORIZONS = (30, 60, 90)


class SettlementMethod(StrEnum):
    PIX = "PIX"
    TRANSFER = "TRANSFER"
    BANK_SLIP = "BANK_SLIP"
    CASH = "CASH"
    DEBIT_CARD = "DEBIT_CARD"
    CREDIT_CARD = "CREDIT_CARD"


class Granularity(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"


@dataclass(frozen=True, slots=True)
class ManualEntryInput:
    category_id: int | None
    description: str
    amount: Decimal | None
    due_date: date | None
    supplier_id: int | None = None
    customer_id: int | None = None
    repeat_months: int = 1


@dataclass(frozen=True, slots=True)
class ScheduledEntry:
    description: str
    accrual_date: date
    due_date: date


@dataclass(frozen=True, slots=True)
class SettlementInput:
    entry_ids: tuple[int, ...]
    account_id: int | None
    method: SettlementMethod
    settled_date: date | None = None


@dataclass(frozen=True, slots=True)
class CashMovement:
    day: date
    account_id: int
    entry_type: EntryType
    amount: Decimal

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.entry_type is EntryType.RECEIVABLE else -self.amount


@dataclass(frozen=True, slots=True)
class CashFlowPeriod:
    start: date
    inflow: Decimal
    outflow: Decimal
    balance: Decimal

    @property
    def net(self) -> Decimal:
        return self.inflow - self.outflow


@dataclass(frozen=True, slots=True)
class ForecastBucket:
    horizon_days: int
    inflow: Decimal
    outflow: Decimal
    projected_balance: Decimal


def validate_manual_entry(data: ManualEntryInput, dre_group: DreGroup | None, accrual_date: date) -> ManualEntryInput:
    if data.category_id is None or dre_group is None:
        raise BusinessRuleError("Selecione a categoria.")
    if dre_group not in MANUAL_ENTRY_GROUPS:
        raise BusinessRuleError("Lançamentos manuais só usam categorias de despesa operacional ou de outras receitas.")
    if data.amount is None or data.amount <= 0:
        raise BusinessRuleError("O valor deve ser maior que zero.")
    if data.due_date is None:
        raise BusinessRuleError("Informe o vencimento.")
    if not 1 <= data.repeat_months <= MAX_RECURRENCE_MONTHS:
        raise BusinessRuleError(f"A recorrência vai de 1 a {MAX_RECURRENCE_MONTHS} meses.")
    if data.due_date < accrual_date - timedelta(days=365):
        raise BusinessRuleError("O vencimento está distante demais da competência. Confira a data.")
    description = require_text(data.description, "Informe a descrição.")
    return replace(data, description=description, amount=round_money(data.amount))


def schedule_entries(data: ManualEntryInput, accrual_date: date) -> list[ScheduledEntry]:
    """Monthly recurrence repeats the accrual and due dates, labelling each occurrence."""
    if data.repeat_months == 1:
        return [ScheduledEntry(data.description, accrual_date, data.due_date)]
    return [
        ScheduledEntry(
            f"{data.description} ({index + 1}/{data.repeat_months})",
            add_months(accrual_date, index),
            add_months(data.due_date, index),
        )
        for index in range(data.repeat_months)
    ]


def ensure_settlement_date(status: EntryStatus, accrual_date: date, settled_date: date, today: date) -> None:
    """RN-22: only pending entries settle, on a date between the accrual and today."""
    if status is not EntryStatus.PENDING:
        raise BusinessRuleError("Só títulos pendentes podem ser liquidados.")
    if settled_date > today:
        raise BusinessRuleError("A data da liquidação não pode estar no futuro.")
    if settled_date < accrual_date:
        raise BusinessRuleError("A data da liquidação não pode ser anterior à competência do título.")


def ensure_settlement_reversible(status: EntryStatus, is_reconciled: bool) -> None:
    if status is not EntryStatus.SETTLED:
        raise BusinessRuleError("Só títulos liquidados podem ter a liquidação estornada.")
    if is_reconciled:
        raise BusinessRuleError("Este título já foi conciliado. Desfaça a conciliação antes de estornar.")


def period_start(day: date, granularity: Granularity) -> date:
    if granularity is Granularity.DAY:
        return day
    if granularity is Granularity.WEEK:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def build_cash_flow(
    movements: list[CashMovement], opening_balance: Decimal, granularity: Granularity
) -> list[CashFlowPeriod]:
    """RF-FIN-04: realised inflows and outflows per period with the running balance."""
    totals: dict[date, tuple[Decimal, Decimal]] = {}
    for movement in movements:
        start = period_start(movement.day, granularity)
        inflow, outflow = totals.get(start, (Decimal("0"), Decimal("0")))
        if movement.entry_type is EntryType.RECEIVABLE:
            inflow += movement.amount
        else:
            outflow += movement.amount
        totals[start] = (inflow, outflow)
    balance = opening_balance
    periods = []
    for start in sorted(totals):
        inflow, outflow = totals[start]
        balance += inflow - outflow
        periods.append(CashFlowPeriod(start, inflow, outflow, balance))
    return periods


def build_forecast(
    pending: list[tuple[date, EntryType, Decimal]], current_balance: Decimal, today: date
) -> list[ForecastBucket]:
    """Pending entries due up to each horizon (overdue ones count as due now) and the projected balance."""
    buckets = []
    for horizon in FORECAST_HORIZONS:
        limit = today + timedelta(days=horizon)
        due = [(entry_type, amount) for due_date, entry_type, amount in pending if due_date <= limit]
        inflow = sum((amount for entry_type, amount in due if entry_type is EntryType.RECEIVABLE), Decimal("0"))
        outflow = sum((amount for entry_type, amount in due if entry_type is EntryType.PAYABLE), Decimal("0"))
        buckets.append(ForecastBucket(horizon, inflow, outflow, current_balance + inflow - outflow))
    return buckets


@dataclass(frozen=True, slots=True)
class IncomeStatement:
    """RF-FIN-06: accrual result. Stock purchases stay out; they reach the result as cost of goods sold."""

    month: date
    net_revenue: Decimal
    freight_revenue: Decimal
    other_revenue: Decimal
    cost_of_goods: Decimal
    selling_costs: Decimal
    stock_adjustments: Decimal
    operating_expenses: Decimal

    @property
    def total_revenue(self) -> Decimal:
        return self.net_revenue + self.freight_revenue + self.other_revenue

    @property
    def gross_profit(self) -> Decimal:
        return self.total_revenue - self.cost_of_goods

    @property
    def result(self) -> Decimal:
        return self.gross_profit - self.selling_costs + self.stock_adjustments - self.operating_expenses

    @property
    def gross_margin_pct(self) -> Decimal | None:
        if self.net_revenue <= 0:
            return None
        return ((self.net_revenue - self.cost_of_goods) / self.net_revenue * 100).quantize(Decimal("0.1"))


def sum_statements(month: date, statements: list[IncomeStatement]) -> IncomeStatement:
    fields = ("net_revenue", "freight_revenue", "other_revenue", "cost_of_goods", "selling_costs",
              "stock_adjustments", "operating_expenses")  # fmt: skip
    totals = {field: sum((getattr(item, field) for item in statements), Decimal("0")) for field in fields}
    return IncomeStatement(month, **totals)


def balance_series(
    periods: list[CashFlowPeriod], opening_balance: Decimal, start_date: date, end_date: date, granularity: Granularity
) -> list[tuple[date, Decimal]]:
    """Balance at every period of the range, carrying it forward through periods without movement."""
    by_start = {period.start: period.balance for period in periods}
    series = []
    balance = opening_balance
    current = period_start(start_date, granularity)
    while current <= end_date:
        balance = by_start.get(current, balance)
        series.append((current, balance))
        if granularity is Granularity.MONTH:
            current = add_months(current, 1)
        else:
            current += timedelta(days=7 if granularity is Granularity.WEEK else 1)
    return series
