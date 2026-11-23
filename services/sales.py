from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from psycopg import Connection

from core.clock import today
from core.db import transaction
from core.errors import BusinessRuleError, ConfigurationError
from domain.access import Permission, User, ensure_permission, has_permission
from domain.brazil import PersonType
from domain.dates import resolve_business_date
from domain.effects import EntryChange, OperationEffects, StockChange
from domain.fields import require_text
from domain.finance import AccountKind, EntryType
from domain.inventory import MovementType, SourceModule, StockItemKind, StockItemRef
from domain.numbers import round_money
from domain.partners import Segment
from domain.sales import (
    Channel,
    DeliveryType,
    PaymentMethod,
    SaleCustomer,
    SaleDisplayStatus,
    SaleInput,
    SaleItemInput,
    SaleProduct,
    SalesSettings,
    SaleStatus,
    SaleTotals,
    ShipmentInput,
    box_count,
    ensure_credit_available,
    ensure_transition,
    gross_margin_pct,
    payment_fee,
    quote_valid_until,
    receivable_terms,
    validate_sale,
    validate_shipment,
)
from repositories import finance as finance_repository
from repositories import inventory as inventory_repository
from repositories import sales as sales_repository
from services.finance import require_system_account_id, require_system_category_id
from services.inventory import MovementRequest, record_movement
from services.parameters import decimal_settings, optional_int_setting

REVENUE_CATEGORY = "Venda de cafés"
FEE_CATEGORY = "Taxas de meios de pagamento"
FREIGHT_CATEGORY = "Fretes sobre vendas"
REFUND_CATEGORY = "Reembolso a clientes"
FREIGHT_TERM_DAYS = 30
SHIPPING_BOX_SETTING = "default_shipping_box_id"
INT_SETTINGS = (
    "quote_validity_days",
    "wholesale_default_term_days",
    "overdue_tolerance_days",
    "credit_card_term_days",
    "debit_card_term_days",
)
DECIMAL_SETTINGS = ("max_discount_pct", "wholesale_min_order_kg", "credit_card_fee_pct", "debit_card_fee_pct")
SETTLEMENT_ACCOUNTS = {PaymentMethod.PIX: AccountKind.BANK, PaymentMethod.CASH: AccountKind.CASH}


@dataclass(frozen=True, slots=True)
class SaleFilters:
    start_date: date
    end_date: date
    channels: tuple[Channel, ...]
    statuses: tuple[SaleDisplayStatus, ...]
    customer_id: int | None = None


@dataclass(frozen=True, slots=True)
class SaleResult:
    sale_id: int
    number: str
    status: SaleStatus
    effects: OperationEffects | None = None
    net_revenue: Decimal | None = None
    products_cost: Decimal | None = None

    @property
    def margin_pct(self) -> Decimal | None:
        if self.net_revenue is None or self.products_cost is None:
            return None
        return gross_margin_pct(self.net_revenue, self.products_cost)


@dataclass(frozen=True, slots=True)
class SaleDetail:
    sale: dict[str, Any]
    items: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    movements: list[dict[str, Any]]
    events: list[dict[str, Any]]
    customer_history: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ShippingBox:
    id: int
    name: str
    capacity_g: int


@dataclass(frozen=True, slots=True)
class SaleFormContext:
    settings: SalesSettings
    shipping_box: ShippingBox | None
    customers: list[dict[str, Any]]
    products: list[dict[str, Any]]


def _settings(connection: Connection) -> SalesSettings:
    values = decimal_settings(connection, [*INT_SETTINGS, *DECIMAL_SETTINGS])
    return SalesSettings(
        **{key: int(values[key]) for key in INT_SETTINGS}, **{key: values[key] for key in DECIMAL_SETTINGS}
    )


def _shipping_box(connection: Connection) -> ShippingBox | None:
    row = sales_repository.find_shipping_box(connection, optional_int_setting(connection, SHIPPING_BOX_SETTING))
    return ShippingBox(row["id"], row["name"], row["capacity_g"]) if row else None


def _sale_customer(row: dict[str, Any] | None) -> SaleCustomer | None:
    if row is None:
        return None
    return SaleCustomer(
        row["name"],
        PersonType(row["person_type"]),
        Segment(row["segment"]),
        row["is_active"],
        row["payment_term_days"],
        row["credit_limit"],
    )


def _sale_products(connection: Connection, data: SaleInput) -> dict[int, SaleProduct]:
    rows = sales_repository.find_sale_products(connection, [item.product_id for item in data.items])
    return {
        row["id"]: SaleProduct(
            row["id"], row["label"], row["weight_g"], row["price_local"], row["price_online"],
            row["price_wholesale"], row["is_active"],
        )
        for row in rows
    }  # fmt: skip


def _validated(connection: Connection, actor: User, data: SaleInput, settings: SalesSettings) -> tuple:
    customer = _sale_customer(
        sales_repository.find_customer(connection, data.customer_id) if data.customer_id else None
    )
    return validate_sale(
        data,
        customer,
        _sale_products(connection, data),
        settings,
        has_permission(actor, Permission.APPROVE_DISCOUNTS),
    )


def _sale_values(data: SaleInput, totals: SaleTotals) -> dict[str, Any]:
    return {
        "customer_id": data.customer_id,
        "channel": data.channel.value,
        "delivery_type": data.delivery_type.value,
        "payment_method": data.payment_method.value,
        "products_amount": totals.products_amount,
        "discount_amount": totals.discount_amount,
        "freight_amount": totals.freight_amount,
        "total_weight_g": totals.total_weight_g,
        "delivery_address": data.delivery_address,
        "notes": data.notes,
    }


def _save_items(connection: Connection, sale_id: int, items: list) -> None:
    sales_repository.delete_sale_items(connection, sale_id)
    for item in items:
        sales_repository.insert_sale_item(connection, sale_id, item.product_id, item.quantity, item.unit_price)


def _load_sale(connection: Connection, sale_id: int) -> dict[str, Any]:
    sale = sales_repository.find_sale(connection, sale_id, today(), for_update=True)
    if sale is None:
        raise BusinessRuleError("Venda não encontrada. Atualize a página e tente de novo.")
    return sale


def _stored_input(connection: Connection, sale: dict[str, Any]) -> SaleInput:
    items = sales_repository.list_sale_items(connection, sale["id"])
    return SaleInput(
        customer_id=sale["customer_id"],
        channel=Channel(sale["channel"]),
        delivery_type=DeliveryType(sale["delivery_type"]),
        payment_method=PaymentMethod(sale["payment_method"]),
        items=tuple(SaleItemInput(item["product_id"], item["quantity"]) for item in items),
        discount_amount=sale["discount_amount"],
        freight_amount=sale["freight_amount"],
        delivery_address=sale["delivery_address"],
        notes=sale["notes"],
    )


def _business_date(actor: User, requested: date | None) -> date:
    return resolve_business_date(requested, today(), has_permission(actor, Permission.BACKDATE_OPERATIONS))


def _entry_values(actor: User, sale: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {
        "source_module": SourceModule.SALES.value,
        "source_id": sale["id"],
        "user_email": actor.email,
        **values,
    }


def _record(connection: Connection, actor: User, item: StockItemRef, movement_type: MovementType, quantity: Decimal,
            movement_date: date, sale_id: int, unit_cost: Decimal | None = None) -> StockChange:  # fmt: skip
    return record_movement(
        connection,
        actor.email,
        MovementRequest(item, movement_type, quantity, movement_date, SourceModule.SALES, sale_id, unit_cost=unit_cost),
    )


def _create_receivables(
    connection: Connection, actor: User, sale: dict[str, Any], data: SaleInput, total: Decimal, sale_date: date,
    settings: SalesSettings, customer: dict[str, Any],
) -> tuple[list[EntryChange], Decimal]:  # fmt: skip
    terms = receivable_terms(data.payment_method, customer["payment_term_days"], settings)
    due_date = sale_date + timedelta(days=terms.due_days)
    description = f"Venda {sale['number']}"
    values = _entry_values(
        actor, sale,
        entry_type=EntryType.RECEIVABLE.value,
        category_id=require_system_category_id(connection, REVENUE_CATEGORY),
        description=description, amount=total, accrual_date=sale_date, due_date=due_date,
        customer_id=data.customer_id,
    )  # fmt: skip
    if terms.settled_on_creation:
        values |= {
            "status": "SETTLED",
            "settled_date": sale_date,
            "account_id": require_system_account_id(connection, SETTLEMENT_ACCOUNTS[data.payment_method].value),
            "settlement_method": data.payment_method.value,
            "settled_by": actor.email,
        }
    entry_id = finance_repository.insert_entry(connection, values)
    action = "settled" if terms.settled_on_creation else "created"
    entries = [EntryChange(entry_id, EntryType.RECEIVABLE, description, total, due_date, action)]
    fee = payment_fee(total, terms.fee_pct)
    if fee > 0:
        fee_description = f"Taxa do cartão · venda {sale['number']}"
        fee_id = finance_repository.insert_entry(
            connection,
            _entry_values(
                actor, sale,
                entry_type=EntryType.PAYABLE.value,
                category_id=require_system_category_id(connection, FEE_CATEGORY),
                description=fee_description, amount=fee, accrual_date=sale_date, due_date=due_date,
            ),
        )  # fmt: skip
        entries.append(EntryChange(fee_id, EntryType.PAYABLE, fee_description, fee, due_date))
    return entries, fee


def _confirm(
    connection: Connection, actor: User, sale: dict[str, Any], sale_date: date, deliver_now: bool
) -> SaleResult:
    """RF-VEN-03: revalidates, takes stock out with cost snapshots and creates the receivables (RN-14, RN-16)."""
    current = SaleStatus(sale["status"])
    ensure_transition(current, SaleStatus.CONFIRMED)
    if sale["display_status"] == SaleDisplayStatus.EXPIRED:
        raise BusinessRuleError(
            f"O orçamento venceu em {sale['quote_valid_until']:%d/%m/%Y}. Atualize os preços antes de confirmar."
        )
    if sale_date < sale["quote_date"]:
        raise BusinessRuleError("A data da venda não pode ser anterior à data do orçamento.")
    settings = _settings(connection)
    data, items, totals = _validated(connection, actor, _stored_input(connection, sale), settings)
    if totals.products_amount != sale["products_amount"]:
        raise BusinessRuleError("Os preços mudaram desde o orçamento. Atualize o orçamento antes de confirmar.")
    customer = sales_repository.find_customer(connection, data.customer_id)
    if data.payment_method is PaymentMethod.BANK_SLIP:
        position = sales_repository.customer_credit_position(connection, data.customer_id, sale_date)
        ensure_credit_available(
            _sale_customer(customer), position["open_amount"], position["max_overdue_days"], totals.total_amount,
            settings,
        )  # fmt: skip
    box = _shipping_box(connection) if data.delivery_type is DeliveryType.SHIPPING else None
    if data.delivery_type is DeliveryType.SHIPPING and box is None:
        raise ConfigurationError("Cadastre uma caixa de envio ativa para vender com envio.")
    boxes = box_count(totals.total_weight_g, data.delivery_type, box.capacity_g if box else 1)
    stock: list[StockChange] = []
    products_cost = Decimal("0")
    for item in sales_repository.list_sale_items(connection, sale["id"]):
        change = _record(
            connection, actor, StockItemRef(StockItemKind.PRODUCT, item["product_id"]), MovementType.SALE_OUT,
            -Decimal(item["quantity"]), sale_date, sale["id"],
        )  # fmt: skip
        sales_repository.set_item_cost_snapshot(connection, item["id"], change.unit_cost)
        products_cost += item["quantity"] * change.unit_cost
        stock.append(change)
    boxes_cost = Decimal("0")
    if boxes:
        change = _record(
            connection, actor, StockItemRef(StockItemKind.PACKAGING_ITEM, box.id), MovementType.SALE_OUT,
            -Decimal(boxes), sale_date, sale["id"],
        )  # fmt: skip
        boxes_cost = boxes * change.unit_cost
        stock.append(change)
    entries, fee = _create_receivables(
        connection, actor, sale, data, totals.total_amount, sale_date, settings, customer
    )
    sales_repository.set_status(
        connection, sale["id"], SaleStatus.CONFIRMED.value,
        {"sale_date": sale_date, "box_count": boxes, "products_cost": round_money(products_cost),
         "boxes_cost": round_money(boxes_cost), "payment_fee": fee},
    )  # fmt: skip
    sales_repository.insert_event(connection, sale["id"], current.value, SaleStatus.CONFIRMED.value, None, actor.email)
    status = SaleStatus.CONFIRMED
    if deliver_now and data.delivery_type is DeliveryType.PICKUP:
        _deliver(connection, actor, sale["id"], status, "Retirado no balcão")
        status = SaleStatus.DELIVERED
    return SaleResult(
        sale["id"], sale["number"], status, OperationEffects(stock=stock, entries=entries), totals.net_revenue,
        round_money(products_cost),
    )  # fmt: skip


def _deliver(connection: Connection, actor: User, sale_id: int, current: SaleStatus, notes: str | None) -> None:
    ensure_transition(current, SaleStatus.DELIVERED)
    sales_repository.set_status(connection, sale_id, SaleStatus.DELIVERED.value)
    sales_repository.insert_event(connection, sale_id, current.value, SaleStatus.DELIVERED.value, notes, actor.email)


def create_sale(
    actor: User, data: SaleInput, confirm: bool = False, deliver_now: bool = False, sale_date: date | None = None
) -> SaleResult:
    """Saves a quote (RF-VEN-02) or, with confirm, invoices it in the same transaction."""
    ensure_permission(actor, Permission.MANAGE_SALES)
    quote_date = _business_date(actor, sale_date)
    with transaction(actor.email) as connection:
        settings = _settings(connection)
        data, items, totals = _validated(connection, actor, data, settings)
        number = sales_repository.next_sale_number(connection, quote_date.year)
        sale_id = sales_repository.insert_sale(
            connection,
            {
                **_sale_values(data, totals),
                "number": number,
                "quote_date": quote_date,
                "quote_valid_until": quote_valid_until(quote_date, settings),
                "user_email": actor.email,
            },
        )
        _save_items(connection, sale_id, items)
        sales_repository.insert_event(connection, sale_id, None, SaleStatus.QUOTE.value, None, actor.email)
        if not confirm:
            return SaleResult(sale_id, number, SaleStatus.QUOTE)
        return _confirm(connection, actor, _load_sale(connection, sale_id), quote_date, deliver_now)


def update_quote(actor: User, sale_id: int, data: SaleInput) -> None:
    """Editing a quote reloads catalog prices and restarts its validity."""
    ensure_permission(actor, Permission.MANAGE_SALES)
    with transaction(actor.email) as connection:
        sale = _load_sale(connection, sale_id)
        ensure_transition(SaleStatus(sale["status"]), SaleStatus.QUOTE)
        settings = _settings(connection)
        data, items, totals = _validated(connection, actor, data, settings)
        sales_repository.update_sale(
            connection,
            sale_id,
            {**_sale_values(data, totals), "quote_valid_until": quote_valid_until(today(), settings)},
        )
        _save_items(connection, sale_id, items)


def refresh_quote(actor: User, sale_id: int) -> None:
    """RN-25: an expired quote is brought back with current prices before it can be confirmed."""
    ensure_permission(actor, Permission.MANAGE_SALES)
    with transaction(actor.email) as connection:
        sale = _load_sale(connection, sale_id)
        stored = _stored_input(connection, sale)
    update_quote(actor, sale_id, stored)


def confirm_sale(actor: User, sale_id: int, deliver_now: bool = False, sale_date: date | None = None) -> SaleResult:
    ensure_permission(actor, Permission.MANAGE_SALES)
    sale_date = _business_date(actor, sale_date)
    with transaction(actor.email) as connection:
        return _confirm(connection, actor, _load_sale(connection, sale_id), sale_date, deliver_now)


def ship_sale(actor: User, sale_id: int, data: ShipmentInput) -> OperationEffects:
    """RF-VEN-04: the real freight becomes a payable so the BI can measure subsidised shipping."""
    ensure_permission(actor, Permission.MANAGE_SALES)
    with transaction(actor.email) as connection:
        sale = _load_sale(connection, sale_id)
        current = SaleStatus(sale["status"])
        ensure_transition(current, SaleStatus.SHIPPED)
        data = validate_shipment(data, DeliveryType(sale["delivery_type"]))
        entries = []
        if data.actual_freight_cost > 0:
            ship_date = today()
            due_date = ship_date + timedelta(days=FREIGHT_TERM_DAYS)
            description = f"Frete da venda {sale['number']} · {data.tracking_code}"
            entry_id = finance_repository.insert_entry(
                connection,
                _entry_values(
                    actor, sale,
                    entry_type=EntryType.PAYABLE.value,
                    category_id=require_system_category_id(connection, FREIGHT_CATEGORY),
                    description=description, amount=data.actual_freight_cost, accrual_date=ship_date,
                    due_date=due_date,
                ),
            )  # fmt: skip
            entries.append(EntryChange(entry_id, EntryType.PAYABLE, description, data.actual_freight_cost, due_date))
        sales_repository.set_status(
            connection, sale_id, SaleStatus.SHIPPED.value,
            {"carrier": data.carrier, "tracking_code": data.tracking_code,
             "actual_freight_cost": data.actual_freight_cost},
        )  # fmt: skip
        notes = f"Rastreio {data.tracking_code}" + (f" · {data.carrier}" if data.carrier else "")
        sales_repository.insert_event(connection, sale_id, current.value, SaleStatus.SHIPPED.value, notes, actor.email)
    return OperationEffects(entries=entries)


def deliver_sale(actor: User, sale_id: int) -> None:
    ensure_permission(actor, Permission.MANAGE_SALES)
    with transaction(actor.email) as connection:
        sale = _load_sale(connection, sale_id)
        current = SaleStatus(sale["status"])
        if current is SaleStatus.CONFIRMED and DeliveryType(sale["delivery_type"]) is DeliveryType.SHIPPING:
            raise BusinessRuleError("Pedidos com envio precisam ser expedidos antes da entrega.")
        _deliver(connection, actor, sale_id, current, None)


def _reverse_stock(connection: Connection, actor: User, sale: dict[str, Any], reversal_date: date) -> list:
    changes = [
        _record(
            connection, actor, StockItemRef(StockItemKind.PRODUCT, item["product_id"]), MovementType.SALE_REVERSAL,
            Decimal(item["quantity"]), reversal_date, sale["id"], item["unit_cost_snapshot"],
        )
        for item in sales_repository.list_sale_items(connection, sale["id"])
    ]  # fmt: skip
    box_movements = inventory_repository.list_source_movements(
        connection, SourceModule.SALES.value, sale["id"], [MovementType.SALE_OUT.value]
    )
    changes += [
        _record(
            connection, actor, StockItemRef(StockItemKind.PACKAGING_ITEM, movement["item_id"]),
            MovementType.SALE_REVERSAL, -movement["quantity"], reversal_date, sale["id"], movement["unit_cost"],
        )
        for movement in box_movements
        if movement["item_kind"] == StockItemKind.PACKAGING_ITEM
    ]  # fmt: skip
    return changes


def cancel_sale(actor: User, sale_id: int, reason: str) -> OperationEffects:
    """RF-VEN-06: quotes cancel freely; confirmed sales are reversed in stock and finance by a manager."""
    ensure_permission(actor, Permission.MANAGE_SALES)
    reason = require_text(reason, "Informe o motivo do cancelamento.")
    with transaction(actor.email) as connection:
        sale = _load_sale(connection, sale_id)
        current = SaleStatus(sale["status"])
        if current is SaleStatus.SHIPPED:
            raise BusinessRuleError("Pedidos expedidos não podem ser cancelados. Devoluções estão fora do escopo.")
        ensure_transition(current, SaleStatus.CANCELLED)
        effects = OperationEffects()
        if current is SaleStatus.CONFIRMED:
            ensure_permission(actor, Permission.CANCEL_SALES)
            reversal_date = today()
            effects.stock = _reverse_stock(connection, actor, sale, reversal_date)
            effects.entries = _cancel_entries(connection, actor, sale, reason, reversal_date)
        sales_repository.set_status(connection, sale_id, SaleStatus.CANCELLED.value, {"cancel_reason": reason})
        sales_repository.insert_event(
            connection, sale_id, current.value, SaleStatus.CANCELLED.value, reason, actor.email
        )
    return effects


def _cancel_entries(
    connection: Connection, actor: User, sale: dict[str, Any], reason: str, cancel_date: date
) -> list[EntryChange]:
    cancelled = finance_repository.cancel_source_entries(
        connection, SourceModule.SALES.value, sale["id"], f"Cancelamento da venda {sale['number']}: {reason}",
        actor.email,
    )  # fmt: skip
    entries = [
        EntryChange(row["id"], EntryType(row["entry_type"]), row["description"], row["amount"], row["due_date"],
                    "cancelled")
        for row in cancelled
    ]  # fmt: skip
    settled = finance_repository.list_settled_source_entries(
        connection, SourceModule.SALES.value, sale["id"], EntryType.RECEIVABLE.value
    )
    for row in settled:
        description = f"Reembolso da venda {sale['number']}"
        entry_id = finance_repository.insert_entry(
            connection,
            _entry_values(
                actor, sale,
                entry_type=EntryType.PAYABLE.value,
                category_id=require_system_category_id(connection, REFUND_CATEGORY),
                description=description, amount=row["amount"], accrual_date=cancel_date, due_date=cancel_date,
                customer_id=sale["customer_id"],
            ),
        )  # fmt: skip
        entries.append(EntryChange(entry_id, EntryType.PAYABLE, description, row["amount"], cancel_date))
    return entries


def list_sales(actor: User, filters: SaleFilters) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_SALES)
    if filters.start_date > filters.end_date:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")
    with transaction(actor.email) as connection:
        return sales_repository.list_sales(
            connection,
            filters.start_date,
            filters.end_date,
            [channel.value for channel in filters.channels],
            [status.value for status in filters.statuses],
            filters.customer_id,
            today(),
        )


def get_sale_detail(actor: User, sale_id: int) -> SaleDetail:
    ensure_permission(actor, Permission.VIEW_SALES)
    with transaction(actor.email) as connection:
        sale = sales_repository.find_sale(connection, sale_id, today())
        if sale is None:
            raise BusinessRuleError("Venda não encontrada.")
        return SaleDetail(
            sale=sale,
            items=sales_repository.list_sale_items(connection, sale_id),
            entries=finance_repository.list_source_entries(connection, SourceModule.SALES.value, sale_id, today()),
            movements=inventory_repository.list_source_movements(connection, SourceModule.SALES.value, sale_id),
            events=sales_repository.list_events(connection, sale_id),
            customer_history=sales_repository.customer_history(connection, sale["customer_id"]),
        )


def get_sale_form_context(actor: User, include_customer_id: int | None = None) -> SaleFormContext:
    ensure_permission(actor, Permission.MANAGE_SALES)
    with transaction(actor.email) as connection:
        return SaleFormContext(
            settings=_settings(connection),
            shipping_box=_shipping_box(connection),
            customers=sales_repository.list_customer_options(connection, include_customer_id),
            products=sales_repository.list_sale_products(connection),
        )


def get_customer_options(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_SALES)
    with transaction(actor.email) as connection:
        return sales_repository.list_customer_options(connection)
