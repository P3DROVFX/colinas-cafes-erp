from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from psycopg import Connection

from core.clock import today
from core.db import transaction
from core.errors import BusinessRuleError, ConfigurationError
from domain.access import Permission, User, ensure_permission, has_permission
from domain.dates import resolve_business_date
from domain.fields import require_text
from domain.finance import (
    FORECAST_HORIZONS,
    CashFlowPeriod,
    CashMovement,
    DreGroup,
    EntryDisplayStatus,
    EntryStatus,
    EntryType,
    ForecastBucket,
    Granularity,
    IncomeStatement,
    ManualEntryInput,
    SettlementInput,
    build_cash_flow,
    build_forecast,
    ensure_settlement_date,
    ensure_settlement_reversible,
    schedule_entries,
    validate_manual_entry,
)
from domain.inventory import SourceModule
from domain.partners import SupplyType
from repositories import finance as finance_repository
from repositories import partners as partners_repository
from repositories import reports as reports_repository
from repositories import sales as sales_repository


def require_system_category_id(connection: Connection, name: str) -> int:
    category_id = finance_repository.find_system_category_id(connection, name)
    if category_id is None:
        raise ConfigurationError(f"Categoria de sistema ausente: {name}.")
    return category_id


def require_system_account_id(connection: Connection, kind: str) -> int:
    account_id = finance_repository.find_system_account_id(connection, kind)
    if account_id is None:
        raise ConfigurationError("Conta financeira do sistema ausente. Revise as contas cadastradas.")
    return account_id


@dataclass(frozen=True, slots=True)
class EntryFilters:
    due_from: date
    due_to: date
    entry_type: EntryType | None
    statuses: tuple[EntryDisplayStatus, ...]


def list_entries(actor: User, filters: EntryFilters) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_FINANCE)
    if filters.due_from > filters.due_to:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")
    with transaction(actor.email) as connection:
        return finance_repository.list_entries(
            connection,
            today(),
            filters.due_from,
            filters.due_to,
            filters.entry_type.value if filters.entry_type else None,
            [status.value for status in filters.statuses],
        )


@dataclass(frozen=True, slots=True)
class CashFlowRequest:
    start_date: date
    end_date: date
    account_ids: tuple[int, ...]
    granularity: Granularity


@dataclass(frozen=True, slots=True)
class CashFlowReport:
    opening_balance: Decimal
    periods: list[CashFlowPeriod]
    forecast: list[ForecastBucket]

    @property
    def inflow(self) -> Decimal:
        return sum((period.inflow for period in self.periods), Decimal("0"))

    @property
    def outflow(self) -> Decimal:
        return sum((period.outflow for period in self.periods), Decimal("0"))

    @property
    def closing_balance(self) -> Decimal:
        return self.opening_balance + self.inflow - self.outflow


@dataclass(frozen=True, slots=True)
class EntryFormOptions:
    categories: list[dict[str, Any]]
    suppliers: list[dict[str, Any]]
    customers: list[dict[str, Any]]


def _ensure_period(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")


def get_entry_form_options(actor: User) -> EntryFormOptions:
    ensure_permission(actor, Permission.MANAGE_FINANCE)
    with transaction(actor.email) as connection:
        suppliers = [
            row for supply_type in SupplyType
            for row in partners_repository.list_supplier_options(connection, supply_type)
        ]  # fmt: skip
        return EntryFormOptions(
            finance_repository.list_manual_categories(connection),
            sorted(suppliers, key=lambda row: row["name"]),
            sales_repository.list_customer_options(connection),
        )


def create_manual_entry(actor: User, data: ManualEntryInput, accrual_date: date | None = None) -> list[int]:
    """RF-FIN-02: operating expenses and other revenue, optionally repeated monthly."""
    ensure_permission(actor, Permission.MANAGE_FINANCE)
    accrual_date = resolve_business_date(accrual_date, today(), has_permission(actor, Permission.BACKDATE_OPERATIONS))
    with transaction(actor.email) as connection:
        category = finance_repository.find_category(connection, data.category_id) if data.category_id else None
        if category is not None and not category["is_active"]:
            raise BusinessRuleError("Esta categoria está inativa.")
        data = validate_manual_entry(data, DreGroup(category["dre_group"]) if category else None, accrual_date)
        entry_type = EntryType(category["entry_type"])
        schedule = schedule_entries(data, accrual_date)
        return [
            finance_repository.insert_entry(
                connection,
                {
                    "entry_type": entry_type.value,
                    "category_id": data.category_id,
                    "description": occurrence.description,
                    "amount": data.amount,
                    "accrual_date": occurrence.accrual_date,
                    "due_date": occurrence.due_date,
                    "installment": index + 1,
                    "installment_count": len(schedule),
                    "source_module": SourceModule.MANUAL.value,
                    "supplier_id": data.supplier_id if entry_type is EntryType.PAYABLE else None,
                    "customer_id": data.customer_id if entry_type is EntryType.RECEIVABLE else None,
                    "user_email": actor.email,
                },
            )
            for index, occurrence in enumerate(schedule)
        ]


def settle_entries(actor: User, data: SettlementInput) -> int:
    """RF-FIN-03: settles one or many pending entries into an active account, all or nothing."""
    ensure_permission(actor, Permission.MANAGE_FINANCE)
    if not data.entry_ids:
        raise BusinessRuleError("Selecione pelo menos um título.")
    if data.account_id is None:
        raise BusinessRuleError("Selecione a conta financeira.")
    settled_date = data.settled_date or today()
    with transaction(actor.email) as connection:
        account = finance_repository.find_account(connection, data.account_id)
        if account is None or not account["is_active"]:
            raise BusinessRuleError("A conta escolhida está inativa.")
        entries = finance_repository.find_entries(connection, list(data.entry_ids), for_update=True)
        if len(entries) != len(set(data.entry_ids)):
            raise BusinessRuleError("Algum título não foi encontrado. Atualize a página.")
        for entry in entries:
            ensure_settlement_date(EntryStatus(entry["status"]), entry["accrual_date"], settled_date, today())
            finance_repository.settle_entry(
                connection, entry["id"], settled_date, data.account_id, data.method.value, actor.email
            )
    return len(entries)


def _locked_entry(connection: Connection, entry_id: int) -> dict[str, Any]:
    entries = finance_repository.find_entries(connection, [entry_id], for_update=True)
    if not entries:
        raise BusinessRuleError("Título não encontrado. Atualize a página.")
    return entries[0]


def reverse_settlement(actor: User, entry_id: int) -> None:
    ensure_permission(actor, Permission.REVERSE_SETTLEMENTS)
    with transaction(actor.email) as connection:
        entry = _locked_entry(connection, entry_id)
        ensure_settlement_reversible(EntryStatus(entry["status"]), entry["is_reconciled"])
        finance_repository.reverse_settlement(connection, entry_id)


def cancel_manual_entry(actor: User, entry_id: int, reason: str) -> None:
    ensure_permission(actor, Permission.MANAGE_FINANCE)
    reason = require_text(reason, "Informe o motivo do cancelamento.")
    with transaction(actor.email) as connection:
        entry = _locked_entry(connection, entry_id)
        if SourceModule(entry["source_module"]) is not SourceModule.MANUAL:
            raise BusinessRuleError("Títulos gerados por compras, colheitas ou vendas são cancelados pelo documento.")
        if EntryStatus(entry["status"]) is not EntryStatus.PENDING:
            raise BusinessRuleError("Só títulos pendentes podem ser cancelados. Estorne a liquidação antes.")
        finance_repository.cancel_entry(connection, entry_id, reason, actor.email)


def list_account_balances(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_FINANCE)
    with transaction(actor.email) as connection:
        return finance_repository.list_account_balances(connection, today())


def get_cash_flow(actor: User, request: CashFlowRequest) -> CashFlowReport:
    """RF-FIN-04: cash basis, so stock purchases count here even though they are not expenses."""
    ensure_permission(actor, Permission.VIEW_FINANCE)
    _ensure_period(request.start_date, request.end_date)
    if not request.account_ids:
        raise BusinessRuleError("Selecione pelo menos uma conta.")
    account_ids = list(request.account_ids)
    with transaction(actor.email) as connection:
        accounts = [row for row in finance_repository.list_account_balances(connection, today())
                    if row["id"] in request.account_ids]  # fmt: skip
        opening = sum((row["opening_balance"] for row in accounts), Decimal("0"))
        opening += finance_repository.settled_total_before(connection, account_ids, request.start_date)
        settled = finance_repository.list_settled_entries(connection, account_ids, request.start_date, request.end_date)
        current_balance = sum((row["system_balance"] for row in accounts), Decimal("0"))
        pending = finance_repository.list_pending_entries(connection, today() + timedelta(days=max(FORECAST_HORIZONS)))
    movements = [
        CashMovement(row["settled_date"], row["account_id"], EntryType(row["entry_type"]), row["amount"])
        for row in settled
    ]
    forecast = build_forecast(
        [(row["due_date"], EntryType(row["entry_type"]), row["amount"]) for row in pending], current_balance, today()
    )
    return CashFlowReport(opening, build_cash_flow(movements, opening, request.granularity), forecast)


def list_reconciliation(actor: User, account_id: int, start_date: date, end_date: date) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_FINANCE)
    _ensure_period(start_date, end_date)
    with transaction(actor.email) as connection:
        return finance_repository.list_settled_entries(connection, [account_id], start_date, end_date)


def set_reconciled(actor: User, entry_ids: list[int], reconciled: bool, reconciled_date: date | None = None) -> None:
    """RF-FIN-05: marks settled entries as checked against the bank statement or the cash count."""
    ensure_permission(actor, Permission.MANAGE_FINANCE)
    if not entry_ids:
        raise BusinessRuleError("Selecione pelo menos um título.")
    reconciled_date = (reconciled_date or today()) if reconciled else None
    with transaction(actor.email) as connection:
        entries = finance_repository.find_entries(connection, entry_ids, for_update=True)
        if any(EntryStatus(entry["status"]) is not EntryStatus.SETTLED for entry in entries):
            raise BusinessRuleError("Só títulos liquidados podem ser conciliados.")
        if reconciled_date and reconciled_date > today():
            raise BusinessRuleError("A data da conciliação não pode estar no futuro.")
        finance_repository.set_reconciled(connection, entry_ids, reconciled_date)


def get_income_statement(actor: User, start_month: date, end_month: date) -> list[IncomeStatement]:
    ensure_permission(actor, Permission.VIEW_FINANCE)
    start = start_month.replace(day=1)
    end = (end_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    _ensure_period(start, end)
    with transaction(actor.email) as connection:
        rows = reports_repository.monthly_income_statement(connection, start, end)
    return [
        IncomeStatement(
            row["month"], row["net_revenue"], row["freight_revenue"], row["other_revenue"], row["cost_of_goods"],
            row["selling_costs"], row["stock_adjustments"], row["operating_expenses"],
        )
        for row in rows
    ]  # fmt: skip
