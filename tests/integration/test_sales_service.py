from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from core.clock import today
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.brazil import PersonType
from domain.effects import EntryChange
from domain.inventory import StockItemKind, StockItemRef
from domain.partners import CustomerInput, Segment
from domain.purchasing import PurchaseStatus
from domain.sales import (
    Channel,
    DeliveryType,
    PaymentMethod,
    SaleDisplayStatus,
    SaleInput,
    SaleItemInput,
    SaleStatus,
    ShipmentInput,
)
from services import integrity as integrity_service
from services import inventory as inventory_service
from services import partners as partners_service
from services import purchases as purchases_service
from services import sales as sales_service
from services.purchases import PurchaseFilters
from tests.integration.demo_catalog import build_stocked_catalog
from ui.documents import purchase_order_pdf, sale_document_pdf


@pytest.fixture
def manager(make_user):
    return make_user(Role.MANAGER)


@pytest.fixture
def catalog(manager):
    return build_stocked_catalog(manager)


@pytest.fixture
def ana(manager):
    return partners_service.create_customer(
        manager, CustomerInput("Ana Souza", PersonType.INDIVIDUAL, Segment.CONSUMER, address="Rua das Flores, 10")
    )


@pytest.fixture
def walk_in(manager):
    return next(row["id"] for row in sales_service.get_customer_options(manager) if row["is_system"])


def online_sale(catalog, customer_id, quantity=2) -> SaleInput:
    return SaleInput(
        customer_id=customer_id,
        channel=Channel.ONLINE,
        delivery_type=DeliveryType.SHIPPING,
        payment_method=PaymentMethod.CREDIT_CARD,
        items=(SaleItemInput(catalog.product_id, quantity),),
        freight_amount=Decimal("18"),
        delivery_address="Rua das Flores, 10",
    )


def counter_sale(catalog, customer_id, method=PaymentMethod.PIX, quantity=1) -> SaleInput:
    return SaleInput(
        customer_id=customer_id,
        channel=Channel.LOCAL,
        delivery_type=DeliveryType.PICKUP,
        payment_method=method,
        items=(SaleItemInput(catalog.product_id, quantity),),
    )


def stock(manager, kind, item_id) -> Decimal:
    return inventory_service.get_stock_balance(manager, StockItemRef(kind, item_id)).stock


def table_counts(database_url) -> dict[str, int]:
    tables = ("sales", "sale_items", "sale_events", "stock_movements", "financial_entries")
    with psycopg.connect(database_url) as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}


def entry_summary(entries: list[EntryChange]) -> list[tuple]:
    return [(entry.entry_type.value, entry.amount, entry.due_date, entry.action) for entry in entries]


def test_demo_step_6_quote_then_confirm_online_sale(manager, catalog, ana):
    quote = sales_service.create_sale(manager, online_sale(catalog, ana))
    assert quote.status is SaleStatus.QUOTE
    assert stock(manager, StockItemKind.PRODUCT, catalog.product_id) == Decimal("20")

    result = sales_service.confirm_sale(manager, quote.sale_id)
    assert [(change.before, change.after) for change in result.effects.stock] == [
        (Decimal("20"), Decimal("18")),
        (Decimal("50"), Decimal("49")),
    ]
    due = today() + timedelta(days=30)
    assert entry_summary(result.effects.entries) == [
        ("RECEIVABLE", Decimal("127.80"), due, "created"),
        ("PAYABLE", Decimal("4.47"), due, "created"),
    ]
    assert (result.net_revenue, result.products_cost, result.margin_pct) == (
        Decimal("109.80"),
        Decimal("40.01"),
        Decimal("63.6"),
    )
    detail = sales_service.get_sale_detail(manager, quote.sale_id)
    assert detail.sale["total_amount"] == Decimal("127.80")
    assert (detail.sale["box_count"], detail.sale["boxes_cost"], detail.sale["payment_fee"]) == (
        1,
        Decimal("3.20"),
        Decimal("4.47"),
    )
    assert [item["unit_cost_snapshot"] for item in detail.items] == [Decimal("20.0071")]
    assert all(check.passed for check in integrity_service.run_integrity_checks(manager))


def test_demo_step_7_ship_and_deliver(manager, catalog, ana):
    sale = sales_service.create_sale(manager, online_sale(catalog, ana), confirm=True)
    with pytest.raises(BusinessRuleError, match="expedidos antes"):
        sales_service.deliver_sale(manager, sale.sale_id)
    effects = sales_service.ship_sale(manager, sale.sale_id, ShipmentInput("br123456789", Decimal("22"), "Correios"))
    assert entry_summary(effects.entries) == [("PAYABLE", Decimal("22"), today() + timedelta(days=30), "created")]
    with pytest.raises(BusinessRuleError, match="expedidos não podem ser cancelados"):
        sales_service.cancel_sale(manager, sale.sale_id, "Desistência")
    sales_service.deliver_sale(manager, sale.sale_id)
    detail = sales_service.get_sale_detail(manager, sale.sale_id)
    assert [event["to_status"] for event in detail.events] == ["QUOTE", "CONFIRMED", "SHIPPED", "DELIVERED"]
    assert detail.sale["tracking_code"] == "BR123456789"


def test_demo_step_8_counter_pix_sale_is_settled_without_boxes(manager, catalog, walk_in):
    result = sales_service.create_sale(manager, counter_sale(catalog, walk_in), confirm=True, deliver_now=True)
    assert result.status is SaleStatus.DELIVERED
    assert [change.kind for change in result.effects.stock] == [StockItemKind.PRODUCT]
    assert entry_summary(result.effects.entries) == [("RECEIVABLE", Decimal("49.90"), today(), "settled")]
    [entry] = sales_service.get_sale_detail(manager, result.sale_id).entries
    assert entry["status"] == "SETTLED"
    assert stock(manager, StockItemKind.PACKAGING_ITEM, catalog.box_id) == Decimal("50")


def test_demo_step_9_insufficient_stock_records_nothing(manager, catalog, walk_in, database_url):
    before = table_counts(database_url)
    with pytest.raises(BusinessRuleError, match="Estoque insuficiente: CC-BVCAT-MED-GR-250 .* tem 20 un"):
        sales_service.create_sale(manager, counter_sale(catalog, walk_in, quantity=30), confirm=True)
    assert table_counts(database_url) == before


def test_demo_step_14_manager_cancels_confirmed_card_sale(make_user, manager, catalog, walk_in):
    sale = sales_service.create_sale(manager, counter_sale(catalog, walk_in, PaymentMethod.CREDIT_CARD), confirm=True)
    with pytest.raises(AccessDeniedError):
        sales_service.cancel_sale(make_user(Role.SALES), sale.sale_id, "Cliente desistiu")
    effects = sales_service.cancel_sale(manager, sale.sale_id, "Cliente desistiu")
    assert [(change.before, change.after) for change in effects.stock] == [(Decimal("19"), Decimal("20"))]
    assert [entry.action for entry in effects.entries] == ["cancelled", "cancelled"]
    detail = sales_service.get_sale_detail(manager, sale.sale_id)
    assert detail.events[-1]["notes"] == "Cliente desistiu"
    assert {row["status"] for row in detail.entries} == {"CANCELLED"}
    product = inventory_service.get_stock_balance(manager, StockItemRef(StockItemKind.PRODUCT, catalog.product_id))
    assert product.unit_cost == Decimal("20.0071")
    assert all(check.passed for check in integrity_service.run_integrity_checks(manager))


def test_cancelling_settled_sale_creates_refund(manager, catalog, walk_in):
    sale = sales_service.create_sale(manager, counter_sale(catalog, walk_in), confirm=True)
    effects = sales_service.cancel_sale(manager, sale.sale_id, "Pagamento devolvido")
    assert entry_summary(effects.entries) == [("PAYABLE", Decimal("49.90"), today(), "created")]


def test_cancelled_shipping_sale_returns_boxes(manager, catalog, ana):
    sale = sales_service.create_sale(manager, online_sale(catalog, ana), confirm=True)
    sales_service.cancel_sale(manager, sale.sale_id, "Endereço errado")
    assert stock(manager, StockItemKind.PACKAGING_ITEM, catalog.box_id) == Decimal("50")
    assert all(check.passed for check in integrity_service.run_integrity_checks(manager))


def test_sales_role_cancels_quote_and_cannot_confirm_twice(make_user, catalog, ana):
    seller = make_user(Role.SALES)
    quote = sales_service.create_sale(seller, online_sale(catalog, ana))
    sales_service.cancel_sale(seller, quote.sale_id, "Orçamento duplicado")
    with pytest.raises(BusinessRuleError, match="situação atual"):
        sales_service.confirm_sale(seller, quote.sale_id)


def test_expired_quote_needs_refresh(manager, catalog, ana, database_url):
    quote = sales_service.create_sale(manager, online_sale(catalog, ana))
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE sales SET quote_valid_until = %s WHERE id = %s", (today() - timedelta(days=1), quote.sale_id)
        )
    [row] = sales_service.list_sales(
        manager,
        sales_service.SaleFilters(today(), today(), tuple(Channel), tuple(SaleDisplayStatus)),
    )
    assert row["display_status"] == SaleDisplayStatus.EXPIRED
    with pytest.raises(BusinessRuleError, match="venceu"):
        sales_service.confirm_sale(manager, quote.sale_id)
    sales_service.refresh_quote(manager, quote.sale_id)
    assert sales_service.confirm_sale(manager, quote.sale_id).status is SaleStatus.CONFIRMED


def test_price_change_after_quote_blocks_confirmation(manager, catalog, ana, database_url):
    quote = sales_service.create_sale(manager, online_sale(catalog, ana))
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE products SET price_online = 59.90 WHERE id = %s", (catalog.product_id,))
    with pytest.raises(BusinessRuleError, match="preços mudaram"):
        sales_service.confirm_sale(manager, quote.sale_id)


@pytest.fixture
def coffee_shop(manager, catalog, database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE products SET price_wholesale = 40 WHERE id = %s", (catalog.product_id,))
    return partners_service.create_customer(
        manager,
        CustomerInput("Café do Largo", PersonType.COMPANY, Segment.COFFEE_SHOP, "11.222.333/0001-81",
                      address="Praça Central, 5", payment_term_days=21, credit_limit=Decimal("1000")),
    )  # fmt: skip


def wholesale_sale(catalog, customer_id) -> SaleInput:
    return SaleInput(
        customer_id=customer_id,
        channel=Channel.WHOLESALE,
        delivery_type=DeliveryType.LOCAL_DELIVERY,
        payment_method=PaymentMethod.BANK_SLIP,
        items=(SaleItemInput(catalog.product_id, 20),),
        delivery_address="Praça Central, 5",
    )


def test_wholesale_bank_slip_uses_customer_term(manager, catalog, coffee_shop):
    result = sales_service.create_sale(manager, wholesale_sale(catalog, coffee_shop), confirm=True)
    assert entry_summary(result.effects.entries) == [
        ("RECEIVABLE", Decimal("800.00"), today() + timedelta(days=21), "created")
    ]


def test_bank_slip_refused_over_credit_limit_or_when_overdue(manager, catalog, coffee_shop, database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE customers SET credit_limit = 500 WHERE id = %s", (coffee_shop,))
    with pytest.raises(BusinessRuleError, match="Limite de crédito insuficiente"):
        sales_service.create_sale(manager, wholesale_sale(catalog, coffee_shop), confirm=True)
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE customers SET credit_limit = 5000 WHERE id = %s", (coffee_shop,))
        connection.execute(
            """
            INSERT INTO financial_entries (entry_type, category_id, description, amount, accrual_date, due_date,
                                           source_module, customer_id, user_email)
            SELECT 'RECEIVABLE', id, 'Venda antiga', 100, %s, %s, 'MANUAL', %s, 'teste@colinas.com.br'
            FROM financial_categories WHERE name = 'Outras receitas'
            """,
            (today() - timedelta(days=40), today() - timedelta(days=10), coffee_shop),
        )
    with pytest.raises(BusinessRuleError, match="vencido há 10 dias"):
        sales_service.create_sale(manager, wholesale_sale(catalog, coffee_shop), confirm=True)


def test_viewer_reads_sales_but_cannot_sell(make_user, catalog, ana):
    viewer = make_user(Role.VIEWER)
    assert (
        sales_service.list_sales(
            viewer, sales_service.SaleFilters(today(), today(), tuple(Channel), tuple(SaleDisplayStatus))
        )
        == []
    )
    with pytest.raises(AccessDeniedError):
        sales_service.create_sale(viewer, online_sale(catalog, ana))


def test_receipt_and_purchase_order_render_as_pdf(manager, catalog, ana):
    sale = sales_service.create_sale(manager, online_sale(catalog, ana), confirm=True)
    receipt = sale_document_pdf(sales_service.get_sale_detail(manager, sale.sale_id), "Confirmada")
    assert receipt.startswith(b"%PDF")
    [purchase] = purchases_service.list_purchases(
        manager, PurchaseFilters(today(), today(), None, (PurchaseStatus.RECEIVED,))
    )[:1]
    assert purchase_order_pdf(purchases_service.get_purchase_detail(manager, purchase["id"])).startswith(b"%PDF")
