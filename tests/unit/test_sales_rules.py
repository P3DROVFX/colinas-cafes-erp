from datetime import date
from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.brazil import PersonType
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
    ShipmentInput,
    box_count,
    display_status,
    ensure_credit_available,
    ensure_transition,
    gross_margin_pct,
    is_late_shipment,
    payment_fee,
    receivable_terms,
    validate_sale,
    validate_shipment,
)

SETTINGS = SalesSettings(
    quote_validity_days=7,
    max_discount_pct=Decimal("10"),
    wholesale_min_order_kg=Decimal("5"),
    wholesale_default_term_days=28,
    overdue_tolerance_days=5,
    credit_card_fee_pct=Decimal("3.5"),
    credit_card_term_days=30,
    debit_card_fee_pct=Decimal("1.5"),
    debit_card_term_days=1,
)
CONSUMER = SaleCustomer("Ana Souza", PersonType.INDIVIDUAL, Segment.CONSUMER, True, 0, Decimal("0"))
COFFEE_SHOP = SaleCustomer("Café do Largo", PersonType.COMPANY, Segment.COFFEE_SHOP, True, 28, Decimal("2000"))
BAG_250 = SaleProduct(1, "CC-BVCAT-MED-GR-250", 250, Decimal("49.90"), Decimal("54.90"), None, True)
BAG_1000 = SaleProduct(2, "CC-BVCAT-MED-GR-1000", 1000, Decimal("160"), Decimal("170"), Decimal("140"), True)
PRODUCTS = {product.id: product for product in (BAG_250, BAG_1000)}
TODAY = date(2026, 11, 23)


def online_sale(**changes) -> SaleInput:
    values = {
        "customer_id": 1,
        "channel": Channel.ONLINE,
        "delivery_type": DeliveryType.SHIPPING,
        "payment_method": PaymentMethod.CREDIT_CARD,
        "items": (SaleItemInput(1, 2),),
        "freight_amount": Decimal("18"),
        "delivery_address": "Rua das Flores, 10",
    }
    return SaleInput(**(values | changes))


def validate(data: SaleInput, customer=CONSUMER, can_approve=False):
    return validate_sale(data, customer, PRODUCTS, SETTINGS, can_approve)


def test_demo_online_sale_totals():
    _, items, totals = validate(online_sale())
    assert [item.unit_price for item in items] == [Decimal("54.90")]
    assert totals.products_amount == Decimal("109.80")
    assert totals.total_amount == Decimal("127.80")
    assert totals.total_weight_g == 500
    assert payment_fee(totals.total_amount, SETTINGS.credit_card_fee_pct) == Decimal("4.47")


def test_local_sale_uses_counter_price_and_drops_address_on_pickup():
    data, items, _ = validate(
        online_sale(channel=Channel.LOCAL, delivery_type=DeliveryType.PICKUP, payment_method=PaymentMethod.PIX,
                    items=(SaleItemInput(1, 1),), freight_amount=Decimal("0"))
    )  # fmt: skip
    assert items[0].unit_price == Decimal("49.90")
    assert data.delivery_address is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"payment_method": PaymentMethod.CASH}, "forma de pagamento"),
        ({"delivery_type": DeliveryType.PICKUP}, "tipo de entrega"),
        ({"delivery_address": " "}, "endereço"),
        ({"items": ()}, "pelo menos um produto"),
        ({"items": (SaleItemInput(1, 1), SaleItemInput(1, 2))}, "mais de uma vez"),
        ({"items": (SaleItemInput(9, 1),)}, "inativos ou inexistentes"),
        ({"discount_amount": Decimal("120")}, "não pode passar"),
        ({"discount_amount": Decimal("20")}, "precisa de um gerente"),
    ],
)
def test_sale_rules_refuse_invalid_orders(changes, message):
    with pytest.raises(BusinessRuleError, match=message):
        validate(online_sale(**changes))


def test_manager_can_approve_large_discount():
    _, _, totals = validate(online_sale(discount_amount=Decimal("20")), can_approve=True)
    assert totals.total_amount == Decimal("107.80")


def wholesale_sale(**changes) -> SaleInput:
    values = {
        "channel": Channel.WHOLESALE,
        "delivery_type": DeliveryType.LOCAL_DELIVERY,
        "payment_method": PaymentMethod.BANK_SLIP,
        "items": (SaleItemInput(2, 6),),
        "freight_amount": Decimal("0"),
    }
    return online_sale(**(values | changes))


def test_wholesale_uses_wholesale_price():
    _, items, totals = validate(wholesale_sale(), COFFEE_SHOP)
    assert items[0].unit_price == Decimal("140")
    assert totals.total_weight_g == 6000


@pytest.mark.parametrize(
    ("data", "customer", "message"),
    [
        (wholesale_sale(), CONSUMER, "pessoa jurídica"),
        (wholesale_sale(items=(SaleItemInput(2, 4),)), COFFEE_SHOP, "pelo menos 5 kg"),
        (wholesale_sale(items=(SaleItemInput(1, 24),)), COFFEE_SHOP, "não tem preço de atacado"),
    ],
)
def test_wholesale_policy(data, customer, message):
    with pytest.raises(BusinessRuleError, match=message):
        validate(data, customer)


@pytest.mark.parametrize(
    ("weight", "delivery", "boxes"),
    [(500, DeliveryType.SHIPPING, 1), (6000, DeliveryType.SHIPPING, 3), (2001, DeliveryType.SHIPPING, 2),
     (6000, DeliveryType.LOCAL_DELIVERY, 0), (500, DeliveryType.PICKUP, 0)],
)  # fmt: skip
def test_box_count_follows_weight_only_for_shipping(weight, delivery, boxes):
    assert box_count(weight, delivery, 2000) == boxes


@pytest.mark.parametrize(
    ("method", "due_days", "fee", "settled"),
    [
        (PaymentMethod.PIX, 0, Decimal("0"), True),
        (PaymentMethod.CASH, 0, Decimal("0"), True),
        (PaymentMethod.DEBIT_CARD, 1, Decimal("1.5"), False),
        (PaymentMethod.CREDIT_CARD, 30, Decimal("3.5"), False),
        (PaymentMethod.BANK_SLIP, 21, Decimal("0"), False),
    ],
)
def test_receivable_terms_by_payment_method(method, due_days, fee, settled):
    terms = receivable_terms(method, 21, SETTINGS)
    assert (terms.due_days, terms.fee_pct, terms.settled_on_creation) == (due_days, fee, settled)


def test_bank_slip_falls_back_to_default_term():
    assert receivable_terms(PaymentMethod.BANK_SLIP, 0, SETTINGS).due_days == 28


def test_credit_check_blocks_overdue_customers_and_exceeded_limit():
    ensure_credit_available(COFFEE_SHOP, Decimal("1000"), 5, Decimal("1000"), SETTINGS)
    with pytest.raises(BusinessRuleError, match="vencido há 6 dias"):
        ensure_credit_available(COFFEE_SHOP, Decimal("0"), 6, Decimal("100"), SETTINGS)
    with pytest.raises(BusinessRuleError, match=r"disponível R\$ 500,00"):
        ensure_credit_available(COFFEE_SHOP, Decimal("1500"), 0, Decimal("840"), SETTINGS)


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (SaleStatus.QUOTE, SaleStatus.CONFIRMED, True),
        (SaleStatus.CONFIRMED, SaleStatus.CONFIRMED, False),
        (SaleStatus.CONFIRMED, SaleStatus.SHIPPED, True),
        (SaleStatus.SHIPPED, SaleStatus.CANCELLED, False),
        (SaleStatus.DELIVERED, SaleStatus.CANCELLED, False),
        (SaleStatus.CANCELLED, SaleStatus.CONFIRMED, False),
    ],
)
def test_status_transitions(current, target, allowed):
    if allowed:
        ensure_transition(current, target)
    else:
        with pytest.raises(BusinessRuleError):
            ensure_transition(current, target)


def test_expired_quote_is_derived():
    assert display_status(SaleStatus.QUOTE, date(2026, 11, 22), TODAY) is SaleDisplayStatus.EXPIRED
    assert display_status(SaleStatus.QUOTE, TODAY, TODAY) is SaleDisplayStatus.QUOTE
    assert display_status(SaleStatus.CONFIRMED, date(2026, 1, 1), TODAY) is SaleDisplayStatus.CONFIRMED


def test_gross_margin_matches_demo():
    assert gross_margin_pct(Decimal("109.80"), Decimal("40.01")) == Decimal("63.6")


def test_shipment_needs_tracking_and_real_freight():
    shipped = validate_shipment(ShipmentInput(" br123456789 ", Decimal("0")), DeliveryType.SHIPPING)
    assert shipped.tracking_code == "BR123456789"
    with pytest.raises(BusinessRuleError, match="rastreio"):
        validate_shipment(ShipmentInput("", Decimal("22")), DeliveryType.SHIPPING)
    with pytest.raises(BusinessRuleError, match="custo real"):
        validate_shipment(ShipmentInput("BR1", None), DeliveryType.SHIPPING)
    with pytest.raises(BusinessRuleError, match="Só pedidos com envio"):
        validate_shipment(ShipmentInput("BR1", Decimal("1")), DeliveryType.PICKUP)


def test_late_shipment_after_two_days():
    assert is_late_shipment(SaleStatus.CONFIRMED, DeliveryType.SHIPPING, date(2026, 11, 20), TODAY)
    assert not is_late_shipment(SaleStatus.CONFIRMED, DeliveryType.SHIPPING, date(2026, 11, 21), TODAY)
    assert not is_late_shipment(SaleStatus.SHIPPED, DeliveryType.SHIPPING, date(2026, 11, 1), TODAY)
