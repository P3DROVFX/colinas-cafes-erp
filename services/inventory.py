from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection

from core.clock import today
from core.db import transaction
from core.errors import BusinessRuleError
from domain.access import Permission, User, ensure_permission, has_permission
from domain.dates import resolve_business_date
from domain.effects import OperationEffects, StockChange
from domain.fields import require_text
from domain.inventory import (
    AdjustmentReason,
    MovementType,
    SourceModule,
    StockBalance,
    StockItemKind,
    StockItemRef,
    adjustment_quantity,
    plan_movement,
)
from repositories import inventory as inventory_repository
from repositories import production as production_repository


@dataclass(frozen=True, slots=True)
class MovementRequest:
    item: StockItemRef
    movement_type: MovementType
    quantity: Decimal
    movement_date: date
    source_module: SourceModule
    source_id: int | None = None
    unit_cost: Decimal | None = None
    reason: AdjustmentReason | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class AdjustmentInput:
    item: StockItemRef
    reason: AdjustmentReason
    notes: str
    counted_stock: Decimal | None = None
    lost_quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    adjustment_date: date | None = None


def lock_balance(connection: Connection, item: StockItemRef) -> StockBalance:
    balance = inventory_repository.find_stock_balance(connection, item, for_update=True)
    if balance is None:
        raise BusinessRuleError("Item de estoque não encontrado.")
    return balance


def record_movement(connection: Connection, user_email: str, request: MovementRequest) -> StockChange:
    """The only code path that changes a stock balance or its average cost (RN-02)."""
    balance = lock_balance(connection, request.item)
    plan = plan_movement(balance, request.movement_type, request.quantity, request.unit_cost, request.reason)
    inventory_repository.update_stock_balance(connection, request.item, plan.new_stock, plan.new_unit_cost)
    inventory_repository.insert_movement(
        connection,
        request.item,
        {
            "movement_date": request.movement_date,
            "movement_type": request.movement_type.value,
            "quantity": plan.quantity,
            "unit_cost": plan.unit_cost,
            "balance_after": plan.new_stock,
            "source_module": request.source_module.value,
            "source_id": request.source_id,
            "reason": request.reason.value if request.reason else None,
            "notes": request.notes,
            "user_email": user_email,
        },
    )
    return StockChange(request.item.kind, balance.label, balance.stock, plan.new_stock, plan.unit_cost)


def list_stock_positions(actor: User, item_kind: StockItemKind) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return inventory_repository.list_stock_positions(connection, item_kind)


def list_stock_items(actor: User, item_kind: StockItemKind) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return inventory_repository.list_stock_items(connection, item_kind)


def get_stock_balance(actor: User, item: StockItemRef) -> StockBalance:
    with transaction(actor.email) as connection:
        balance = inventory_repository.find_stock_balance(connection, item)
    if balance is None:
        raise BusinessRuleError("Item de estoque não encontrado.")
    return balance


def list_item_movements(actor: User, item: StockItemRef, start_date: date, end_date: date) -> list[dict[str, Any]]:
    if start_date > end_date:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")
    with transaction(actor.email) as connection:
        return inventory_repository.list_item_movements(connection, item, start_date, end_date)


def adjust_inventory(actor: User, data: AdjustmentInput) -> OperationEffects:
    ensure_permission(actor, Permission.ADJUST_INVENTORY)
    notes = require_text(data.notes, "Explique o ajuste na observação.")
    adjustment_date = resolve_business_date(
        data.adjustment_date, today(), has_permission(actor, Permission.BACKDATE_OPERATIONS)
    )
    with transaction(actor.email) as connection:
        balance = lock_balance(connection, data.item)
        is_batch = data.item.kind is StockItemKind.ROAST_BATCH
        if is_batch and not production_repository.is_roast_batch_open(connection, data.item.id):
            raise BusinessRuleError(f"O lote {balance.label} está encerrado e não recebe ajustes.")
        quantity = adjustment_quantity(data.reason, balance.stock, data.counted_stock, data.lost_quantity)
        change = record_movement(
            connection,
            actor.email,
            MovementRequest(
                item=data.item,
                movement_type=MovementType.INVENTORY_ADJUSTMENT,
                quantity=quantity,
                movement_date=adjustment_date,
                source_module=SourceModule.INVENTORY,
                unit_cost=data.unit_cost,
                reason=data.reason,
                notes=notes,
            ),
        )
        if is_batch and change.after == 0:
            production_repository.close_roast_batch(connection, data.item.id)
    return OperationEffects(stock=[change])
