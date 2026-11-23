from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from core.clock import today
from core.db import transaction
from domain.access import Permission, User, has_permission
from domain.finance import EntryType
from domain.inventory import StockItemKind, StockStatus, stock_status
from repositories import finance as finance_repository
from repositories import inventory as inventory_repository
from repositories import production as production_repository
from repositories import reports as reports_repository
from services.parameters import int_setting

MINIMUM_STOCK_KINDS = (StockItemKind.GREEN_COFFEE, StockItemKind.PACKAGING_ITEM, StockItemKind.PRODUCT)


@dataclass(frozen=True, slots=True)
class OpenEntries:
    overdue_amount: Decimal = Decimal("0")
    overdue_count: int = 0
    due_soon_amount: Decimal = Decimal("0")
    due_soon_count: int = 0


@dataclass(slots=True)
class HomeSummary:
    """RF-ADM-04: what each role needs to see first, limited to what the role may read."""

    sales: dict[str, Any] | None = None
    payables: OpenEntries | None = None
    receivables: OpenEntries | None = None
    due_alert_days: int = 7
    below_minimum: list[str] = field(default_factory=list)
    stale_batches: list[dict[str, Any]] = field(default_factory=list)
    freshness_days: int = 15


def get_home_summary(actor: User) -> HomeSummary:
    summary = HomeSummary()
    with transaction(actor.email) as connection:
        if has_permission(actor, Permission.VIEW_SALES):
            summary.sales = reports_repository.invoiced_sales_summary(connection, today())
        if has_permission(actor, Permission.VIEW_FINANCE):
            summary.due_alert_days = int_setting(connection, "due_alert_days")
            rows = finance_repository.open_entries_summary(
                connection, today(), today() + timedelta(days=summary.due_alert_days)
            )
            by_type = {
                EntryType(row["entry_type"]): OpenEntries(
                    row["overdue_amount"], row["overdue_count"], row["due_soon_amount"], row["due_soon_count"]
                )
                for row in rows
            }
            summary.payables = by_type.get(EntryType.PAYABLE, OpenEntries())
            summary.receivables = by_type.get(EntryType.RECEIVABLE, OpenEntries())
        summary.below_minimum = [
            row["label"]
            for kind in MINIMUM_STOCK_KINDS
            for row in inventory_repository.list_stock_positions(connection, kind)
            if row["is_active"] and row["min_stock"]
            and stock_status(row["stock"], row["min_stock"]) is not StockStatus.OK
        ]  # fmt: skip
        if has_permission(actor, Permission.VIEW_PRODUCTION):
            summary.freshness_days = int_setting(connection, "roast_batch_alert_days")
            summary.stale_batches = production_repository.list_stale_roast_batches(
                connection, today(), summary.freshness_days
            )
    return summary
