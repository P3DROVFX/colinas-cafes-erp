from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from psycopg import Connection

from core.clock import today
from core.db import transaction
from core.errors import BusinessRuleError, ConfigurationError
from domain.access import Permission, User, ensure_permission, has_permission
from domain.dates import resolve_business_date
from domain.effects import EntryChange, OperationEffects
from domain.fields import require_text
from domain.finance import EntryType, split_installments
from domain.inventory import MovementType, SourceModule, StockItemKind, StockItemRef
from domain.partners import SupplyType
from domain.purchasing import (
    PurchaseInput,
    PurchaseStatus,
    allocate_freight,
    effective_unit_cost,
    item_kind_for_supplier,
    line_amount,
    products_amount,
    validate_purchase,
)
from repositories import finance as finance_repository
from repositories import inventory as inventory_repository
from repositories import partners as partners_repository
from repositories import purchases as purchases_repository
from services.inventory import MovementRequest, record_movement

PURCHASE_CATEGORIES: dict[SupplyType, str] = {
    SupplyType.GREEN_COFFEE: "Compra de café verde",
    SupplyType.PACKAGING: "Compra de embalagens",
}


@dataclass(frozen=True, slots=True)
class PurchaseFilters:
    start_date: date
    end_date: date
    supplier_id: int | None
    statuses: tuple[PurchaseStatus, ...]


@dataclass(frozen=True, slots=True)
class PurchaseDetail:
    purchase: dict[str, Any]
    items: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    movements: list[dict[str, Any]]


def _load_purchase(connection: Connection, purchase_id: int) -> dict[str, Any]:
    purchase = purchases_repository.find_purchase(connection, purchase_id, for_update=True)
    if purchase is None:
        raise BusinessRuleError("Compra não encontrada. Atualize a página e tente de novo.")
    return purchase


def _supply_type(connection: Connection, supplier_id: int | None) -> SupplyType:
    supply_type = partners_repository.find_supplier_supply_type(connection, supplier_id) if supplier_id else None
    if supply_type is None:
        raise BusinessRuleError("Selecione o fornecedor.")
    return supply_type


def _ensure_items_belong_to_supplier(connection: Connection, data: PurchaseInput, supply_type: SupplyType) -> None:
    ids = [item.item_id for item in data.items]
    if item_kind_for_supplier(supply_type) is StockItemKind.GREEN_COFFEE:
        suppliers = purchases_repository.find_coffee_supplier_ids(connection, ids)
        if any(suppliers.get(item_id) != data.supplier_id for item_id in ids):
            raise BusinessRuleError("Só é possível comprar cafés de fazendas parceiras ligadas a este fornecedor.")
    elif len(purchases_repository.find_active_packaging_ids(connection, ids)) != len(ids):
        raise BusinessRuleError("Há embalagens inativas ou inexistentes no pedido.")


def _purchase_values(data: PurchaseInput, order_date: date) -> dict[str, Any]:
    return {
        "supplier_id": data.supplier_id,
        "order_date": order_date,
        "expected_date": data.expected_date,
        "products_amount": products_amount(data.items),
        "freight_amount": data.freight_amount,
        "installments": data.installments,
        "first_due_days": data.first_due_days,
        "supplier_invoice": data.supplier_invoice,
        "notes": data.notes,
    }


def _insert_items(connection: Connection, purchase_id: int, data: PurchaseInput) -> None:
    for item in data.items:
        purchases_repository.insert_purchase_item(
            connection, purchase_id, item.kind, item.item_id, item.quantity, item.unit_cost
        )


def _validated(connection: Connection, data: PurchaseInput, order_date: date) -> PurchaseInput:
    supply_type = _supply_type(connection, data.supplier_id)
    data = validate_purchase(data, supply_type, order_date)
    _ensure_items_belong_to_supplier(connection, data, supply_type)
    return data


def create_purchase(actor: User, data: PurchaseInput, order_date: date | None = None) -> str:
    ensure_permission(actor, Permission.MANAGE_PURCHASES)
    order_date = resolve_business_date(order_date, today(), has_permission(actor, Permission.BACKDATE_OPERATIONS))
    with transaction(actor.email) as connection:
        data = _validated(connection, data, order_date)
        number = purchases_repository.next_purchase_number(connection, order_date.year)
        values = {**_purchase_values(data, order_date), "number": number, "user_email": actor.email}
        purchase_id = purchases_repository.insert_purchase(connection, values)
        _insert_items(connection, purchase_id, data)
    return number


def update_purchase(actor: User, purchase_id: int, data: PurchaseInput) -> None:
    ensure_permission(actor, Permission.MANAGE_PURCHASES)
    with transaction(actor.email) as connection:
        purchase = _load_purchase(connection, purchase_id)
        if PurchaseStatus(purchase["status"]) is not PurchaseStatus.PENDING:
            raise BusinessRuleError("Só é possível editar compras pendentes.")
        data = _validated(connection, data, purchase["order_date"])
        purchases_repository.update_purchase(connection, purchase_id, _purchase_values(data, purchase["order_date"]))
        purchases_repository.delete_purchase_items(connection, purchase_id)
        _insert_items(connection, purchase_id, data)


def _stock_item(item: dict[str, Any]) -> StockItemRef:
    return StockItemRef(StockItemKind(item["item_kind"]), item["item_id"])


def _receive_items(connection: Connection, actor: User, purchase: dict[str, Any], received_date: date) -> list:
    items = purchases_repository.list_purchase_items(connection, purchase["id"])
    freights = allocate_freight(
        [line_amount(item["quantity"], item["unit_cost"]) for item in items], purchase["freight_amount"]
    )
    changes = []
    for item, freight in sorted(zip(items, freights, strict=True), key=lambda pair: pair[0]["item_id"]):
        unit_cost = effective_unit_cost(item["quantity"], item["unit_cost"], freight)
        purchases_repository.set_item_costs(connection, item["id"], freight, unit_cost)
        request = MovementRequest(
            item=_stock_item(item),
            movement_type=MovementType.PURCHASE_IN,
            quantity=item["quantity"],
            movement_date=received_date,
            source_module=SourceModule.PURCHASES,
            source_id=purchase["id"],
            unit_cost=unit_cost,
        )
        changes.append(record_movement(connection, actor.email, request))
    return changes


def _create_payables(
    connection: Connection, actor: User, purchase: dict[str, Any], received_date: date
) -> list[EntryChange]:
    category_name = PURCHASE_CATEGORIES[SupplyType(purchase["supply_type"])]
    category_id = finance_repository.find_system_category_id(connection, category_name)
    if category_id is None:
        raise ConfigurationError(f"Categoria de sistema ausente: {category_name}.")
    total = purchase["products_amount"] + purchase["freight_amount"]
    entries = []
    for installment in split_installments(total, purchase["installments"], received_date, purchase["first_due_days"]):
        description = f"Compra {purchase['number']} · parcela {installment.number}/{installment.count}"
        entry_id = finance_repository.insert_entry(
            connection,
            {
                "entry_type": EntryType.PAYABLE.value,
                "category_id": category_id,
                "description": description,
                "amount": installment.amount,
                "accrual_date": received_date,
                "due_date": installment.due_date,
                "installment": installment.number,
                "installment_count": installment.count,
                "source_module": SourceModule.PURCHASES.value,
                "source_id": purchase["id"],
                "supplier_id": purchase["supplier_id"],
                "user_email": actor.email,
            },
        )
        entries.append(EntryChange(entry_id, EntryType.PAYABLE, description, installment.amount, installment.due_date))
    return entries


def receive_purchase(actor: User, purchase_id: int, received_date: date | None = None) -> OperationEffects:
    ensure_permission(actor, Permission.RECEIVE_PURCHASES)
    received_date = resolve_business_date(received_date, today(), has_permission(actor, Permission.BACKDATE_OPERATIONS))
    with transaction(actor.email) as connection:
        purchase = _load_purchase(connection, purchase_id)
        if PurchaseStatus(purchase["status"]) is not PurchaseStatus.PENDING:
            raise BusinessRuleError(f"A compra {purchase['number']} não está pendente e não pode ser recebida.")
        if received_date < purchase["order_date"]:
            raise BusinessRuleError("A data de recebimento não pode ser anterior à data do pedido.")
        stock = _receive_items(connection, actor, purchase, received_date)
        entries = _create_payables(connection, actor, purchase, received_date)
        purchases_repository.mark_received(connection, purchase_id, received_date, actor.email)
    return OperationEffects(stock=stock, entries=entries)


def cancel_purchase(actor: User, purchase_id: int, reason: str) -> None:
    ensure_permission(actor, Permission.CANCEL_PURCHASES)
    reason = require_text(reason, "Informe o motivo do cancelamento.")
    with transaction(actor.email) as connection:
        purchase = _load_purchase(connection, purchase_id)
        if PurchaseStatus(purchase["status"]) is not PurchaseStatus.PENDING:
            raise BusinessRuleError("Só é possível cancelar compras pendentes. Compras recebidas são estornadas.")
        purchases_repository.mark_closed(connection, purchase_id, PurchaseStatus.CANCELLED, reason, actor.email)


def reverse_purchase(actor: User, purchase_id: int, reason: str) -> OperationEffects:
    ensure_permission(actor, Permission.CANCEL_PURCHASES)
    reason = require_text(reason, "Informe o motivo do estorno.")
    reversal_date = today()
    with transaction(actor.email) as connection:
        purchase = _load_purchase(connection, purchase_id)
        if PurchaseStatus(purchase["status"]) is not PurchaseStatus.RECEIVED:
            raise BusinessRuleError("Só é possível estornar compras recebidas.")
        if finance_repository.count_settled_source_entries(connection, SourceModule.PURCHASES.value, purchase_id):
            raise BusinessRuleError("Esta compra tem parcelas pagas. Estorne os pagamentos antes de estornar a compra.")
        items = purchases_repository.list_purchase_items(connection, purchase_id)
        stock = [
            record_movement(
                connection,
                actor.email,
                MovementRequest(
                    item=_stock_item(item),
                    movement_type=MovementType.PURCHASE_REVERSAL,
                    quantity=-item["quantity"],
                    movement_date=reversal_date,
                    source_module=SourceModule.PURCHASES,
                    source_id=purchase_id,
                    unit_cost=item["effective_unit_cost"],
                    notes=reason,
                ),
            )
            for item in sorted(items, key=lambda row: row["item_id"])
        ]
        cancel_reason = f"Estorno da compra {purchase['number']}: {reason}"
        cancelled = finance_repository.cancel_source_entries(
            connection, SourceModule.PURCHASES.value, purchase_id, cancel_reason, actor.email
        )
        purchases_repository.mark_closed(connection, purchase_id, PurchaseStatus.REVERSED, reason, actor.email)
    entries = [
        EntryChange(
            row["id"], EntryType(row["entry_type"]), row["description"], row["amount"], row["due_date"], "cancelled"
        )
        for row in cancelled
    ]
    return OperationEffects(stock=stock, entries=entries)


def list_purchases(actor: User, filters: PurchaseFilters) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_PURCHASES)
    if filters.start_date > filters.end_date:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")
    with transaction(actor.email) as connection:
        return purchases_repository.list_purchases(
            connection,
            filters.start_date,
            filters.end_date,
            filters.supplier_id,
            [status.value for status in filters.statuses],
        )


def get_purchase_detail(actor: User, purchase_id: int) -> PurchaseDetail:
    ensure_permission(actor, Permission.VIEW_PURCHASES)
    with transaction(actor.email) as connection:
        purchase = purchases_repository.find_purchase(connection, purchase_id)
        if purchase is None:
            raise BusinessRuleError("Compra não encontrada.")
        return PurchaseDetail(
            purchase=purchase,
            items=purchases_repository.list_purchase_items(connection, purchase_id),
            entries=finance_repository.list_source_entries(
                connection, SourceModule.PURCHASES.value, purchase_id, today()
            ),
            movements=inventory_repository.list_source_movements(connection, SourceModule.PURCHASES.value, purchase_id),
        )


def list_purchasable_items(actor: User, supplier_id: int) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_PURCHASES)
    with transaction(actor.email) as connection:
        supply_type = _supply_type(connection, supplier_id)
        if item_kind_for_supplier(supply_type) is StockItemKind.GREEN_COFFEE:
            return purchases_repository.list_purchasable_coffees(connection, supplier_id)
        return purchases_repository.list_purchasable_packaging(connection)


def suggest_expected_date(order_date: date, lead_time_days: int) -> date:
    return order_date + timedelta(days=lead_time_days)
