import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.brazil import PersonType
from domain.fields import clean_text
from domain.numbers import format_decimal, round_money
from domain.partners import Segment

GRAMS_PER_KILOGRAM = 1000
LATE_SHIPPING_DAYS = 2


class Channel(StrEnum):
    LOCAL = "LOCAL"
    ONLINE = "ONLINE"
    WHOLESALE = "WHOLESALE"


class DeliveryType(StrEnum):
    PICKUP = "PICKUP"
    LOCAL_DELIVERY = "LOCAL_DELIVERY"
    SHIPPING = "SHIPPING"


class PaymentMethod(StrEnum):
    PIX = "PIX"
    CASH = "CASH"
    DEBIT_CARD = "DEBIT_CARD"
    CREDIT_CARD = "CREDIT_CARD"
    BANK_SLIP = "BANK_SLIP"


class SaleStatus(StrEnum):
    QUOTE = "QUOTE"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SaleDisplayStatus(StrEnum):
    QUOTE = "QUOTE"
    EXPIRED = "EXPIRED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ChannelRules:
    deliveries: tuple[DeliveryType, ...]
    payments: tuple[PaymentMethod, ...]


CHANNEL_RULES: dict[Channel, ChannelRules] = {
    Channel.LOCAL: ChannelRules(
        (DeliveryType.PICKUP, DeliveryType.LOCAL_DELIVERY),
        (PaymentMethod.PIX, PaymentMethod.CASH, PaymentMethod.DEBIT_CARD, PaymentMethod.CREDIT_CARD),
    ),
    Channel.ONLINE: ChannelRules(
        (DeliveryType.SHIPPING, DeliveryType.LOCAL_DELIVERY), (PaymentMethod.PIX, PaymentMethod.CREDIT_CARD)
    ),
    Channel.WHOLESALE: ChannelRules(
        (DeliveryType.LOCAL_DELIVERY, DeliveryType.SHIPPING), (PaymentMethod.PIX, PaymentMethod.BANK_SLIP)
    ),
}

TRANSITIONS: dict[SaleStatus, frozenset[SaleStatus]] = {
    SaleStatus.QUOTE: frozenset({SaleStatus.QUOTE, SaleStatus.CONFIRMED, SaleStatus.CANCELLED}),
    SaleStatus.CONFIRMED: frozenset({SaleStatus.SHIPPED, SaleStatus.DELIVERED, SaleStatus.CANCELLED}),
    SaleStatus.SHIPPED: frozenset({SaleStatus.DELIVERED}),
    SaleStatus.DELIVERED: frozenset(),
    SaleStatus.CANCELLED: frozenset(),
}

INSTANT_PAYMENTS = frozenset({PaymentMethod.PIX, PaymentMethod.CASH})
CARD_PAYMENTS = frozenset({PaymentMethod.DEBIT_CARD, PaymentMethod.CREDIT_CARD})


@dataclass(frozen=True, slots=True)
class SalesSettings:
    quote_validity_days: int
    max_discount_pct: Decimal
    wholesale_min_order_kg: Decimal
    wholesale_default_term_days: int
    overdue_tolerance_days: int
    credit_card_fee_pct: Decimal
    credit_card_term_days: int
    debit_card_fee_pct: Decimal
    debit_card_term_days: int


@dataclass(frozen=True, slots=True)
class SaleItemInput:
    product_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class SaleInput:
    customer_id: int | None
    channel: Channel
    delivery_type: DeliveryType
    payment_method: PaymentMethod
    items: tuple[SaleItemInput, ...]
    discount_amount: Decimal = Decimal("0")
    freight_amount: Decimal = Decimal("0")
    delivery_address: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SaleCustomer:
    name: str
    person_type: PersonType
    segment: Segment
    is_active: bool
    payment_term_days: int
    credit_limit: Decimal


@dataclass(frozen=True, slots=True)
class SaleProduct:
    id: int
    label: str
    weight_g: int
    price_local: Decimal
    price_online: Decimal
    price_wholesale: Decimal | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class PricedItem:
    product_id: int
    label: str
    quantity: int
    unit_price: Decimal
    weight_g: int

    @property
    def amount(self) -> Decimal:
        return self.quantity * self.unit_price


@dataclass(frozen=True, slots=True)
class SaleTotals:
    products_amount: Decimal
    discount_amount: Decimal
    freight_amount: Decimal
    total_weight_g: int

    @property
    def total_amount(self) -> Decimal:
        return self.products_amount - self.discount_amount + self.freight_amount

    @property
    def net_revenue(self) -> Decimal:
        return self.products_amount - self.discount_amount


@dataclass(frozen=True, slots=True)
class ReceivableTerms:
    due_days: int
    fee_pct: Decimal
    settled_on_creation: bool


def ensure_transition(current: SaleStatus, target: SaleStatus) -> None:
    """RN-23: the sale life cycle follows the state diagram strictly."""
    if target not in TRANSITIONS[current]:
        raise BusinessRuleError("Esta ação não é permitida para a venda na situação atual. Atualize a página.")


def display_status(status: SaleStatus, valid_until: date | None, today: date) -> SaleDisplayStatus:
    if status is SaleStatus.QUOTE and valid_until is not None and valid_until < today:
        return SaleDisplayStatus.EXPIRED
    return SaleDisplayStatus(status.value)


def unit_price(product: SaleProduct, channel: Channel) -> Decimal:
    if channel is Channel.LOCAL:
        return product.price_local
    if channel is Channel.ONLINE:
        return product.price_online
    if product.price_wholesale is None:
        raise BusinessRuleError(f"{product.label} não tem preço de atacado e não pode ser vendido no atacado.")
    return product.price_wholesale


def price_items(
    items: tuple[SaleItemInput, ...], products: dict[int, SaleProduct], channel: Channel
) -> list[PricedItem]:
    if not items:
        raise BusinessRuleError("Inclua pelo menos um produto.")
    seen: set[int] = set()
    priced = []
    for item in items:
        product = products.get(item.product_id)
        if product is None or not product.is_active:
            raise BusinessRuleError("Há produtos inativos ou inexistentes na venda.")
        if item.product_id in seen:
            raise BusinessRuleError(f"{product.label} aparece mais de uma vez. Junte as quantidades numa linha só.")
        if item.quantity is None or item.quantity < 1:
            raise BusinessRuleError(f"Informe a quantidade de {product.label}.")
        seen.add(item.product_id)
        price = unit_price(product, channel)
        priced.append(PricedItem(product.id, product.label, item.quantity, price, product.weight_g))
    return priced


def sale_totals(items: list[PricedItem], discount_amount: Decimal, freight_amount: Decimal) -> SaleTotals:
    return SaleTotals(
        products_amount=sum((item.amount for item in items), Decimal("0")),
        discount_amount=discount_amount,
        freight_amount=freight_amount,
        total_weight_g=sum(item.quantity * item.weight_g for item in items),
    )


def box_count(total_weight_g: int, delivery_type: DeliveryType, box_capacity_g: int) -> int:
    """RN-15: only shipped orders consume boxes, as many as the weight needs."""
    if delivery_type is not DeliveryType.SHIPPING or total_weight_g == 0:
        return 0
    return math.ceil(total_weight_g / box_capacity_g)


def discount_pct(totals: SaleTotals) -> Decimal:
    if totals.products_amount == 0:
        return Decimal("0")
    return totals.discount_amount / totals.products_amount * 100


def needs_discount_approval(totals: SaleTotals, max_discount_pct: Decimal) -> bool:
    return discount_pct(totals) > max_discount_pct


def validate_sale(
    data: SaleInput,
    customer: SaleCustomer | None,
    products: dict[int, SaleProduct],
    settings: SalesSettings,
    can_approve_discount: bool,
) -> tuple[SaleInput, list[PricedItem], SaleTotals]:
    """RN-13 and RN-19: channel policy, catalog prices and discount authority."""
    if customer is None or not customer.is_active:
        raise BusinessRuleError("Selecione um cliente ativo.")
    rules = CHANNEL_RULES[data.channel]
    if data.delivery_type not in rules.deliveries:
        raise BusinessRuleError("Este tipo de entrega não é permitido neste canal.")
    if data.payment_method not in rules.payments:
        raise BusinessRuleError("Esta forma de pagamento não é permitida neste canal.")
    if data.channel is Channel.WHOLESALE and (
        customer.person_type is not PersonType.COMPANY or customer.segment is Segment.CONSUMER
    ):
        raise BusinessRuleError("Atacado só para clientes pessoa jurídica que não sejam consumidores.")
    address = clean_text(data.delivery_address)
    if data.delivery_type is not DeliveryType.PICKUP and not address:
        raise BusinessRuleError("Informe o endereço de entrega.")
    if data.discount_amount is None or data.discount_amount < 0:
        raise BusinessRuleError("O desconto não pode ser negativo.")
    if data.freight_amount is None or data.freight_amount < 0:
        raise BusinessRuleError("O frete cobrado não pode ser negativo.")
    if data.delivery_type is DeliveryType.PICKUP and data.freight_amount > 0:
        raise BusinessRuleError("Pedidos retirados na loja não cobram frete.")
    items = price_items(data.items, products, data.channel)
    totals = sale_totals(items, round_money(data.discount_amount), round_money(data.freight_amount))
    if totals.discount_amount > totals.products_amount:
        raise BusinessRuleError("O desconto não pode passar do valor dos produtos.")
    if totals.total_amount <= 0:
        raise BusinessRuleError("O total do pedido deve ser maior que zero.")
    if needs_discount_approval(totals, settings.max_discount_pct) and not can_approve_discount:
        raise BusinessRuleError(
            f"Desconto acima de {format_decimal(settings.max_discount_pct, 0)}% precisa de um gerente."
        )
    if data.channel is Channel.WHOLESALE:
        minimum_g = settings.wholesale_min_order_kg * GRAMS_PER_KILOGRAM
        if totals.total_weight_g < minimum_g:
            raise BusinessRuleError(
                f"O pedido de atacado precisa de pelo menos {format_decimal(settings.wholesale_min_order_kg, 0)} kg."
            )
    cleaned = replace(data, delivery_address=address if data.delivery_type is not DeliveryType.PICKUP else None,
                      notes=clean_text(data.notes))  # fmt: skip
    return cleaned, items, totals


def receivable_terms(method: PaymentMethod, customer_term_days: int, settings: SalesSettings) -> ReceivableTerms:
    """RN-16: the payment method decides when the money arrives and what it costs."""
    if method in INSTANT_PAYMENTS:
        return ReceivableTerms(0, Decimal("0"), True)
    if method is PaymentMethod.DEBIT_CARD:
        return ReceivableTerms(settings.debit_card_term_days, settings.debit_card_fee_pct, False)
    if method is PaymentMethod.CREDIT_CARD:
        return ReceivableTerms(settings.credit_card_term_days, settings.credit_card_fee_pct, False)
    return ReceivableTerms(customer_term_days or settings.wholesale_default_term_days, Decimal("0"), False)


def payment_fee(total_amount: Decimal, fee_pct: Decimal) -> Decimal:
    return round_money(total_amount * fee_pct / 100)


def ensure_credit_available(
    customer: SaleCustomer, open_amount: Decimal, max_overdue_days: int, order_total: Decimal, settings: SalesSettings
) -> None:
    """RN-20: selling on credit only to customers who pay on time and stay within their limit."""
    if max_overdue_days > settings.overdue_tolerance_days:
        raise BusinessRuleError(
            f"{customer.name} tem título vencido há {max_overdue_days} dias. Venda a prazo bloqueada até a "
            "regularização. Use PIX."
        )
    if open_amount + order_total > customer.credit_limit:
        available = max(customer.credit_limit - open_amount, Decimal("0"))
        raise BusinessRuleError(
            f"Limite de crédito insuficiente: disponível R$ {format_decimal(available, 2)}, pedido "
            f"R$ {format_decimal(order_total, 2)}."
        )


def quote_valid_until(day: date, settings: SalesSettings) -> date:
    return day + timedelta(days=settings.quote_validity_days)


def gross_margin_pct(net_revenue: Decimal, cost_of_goods: Decimal) -> Decimal | None:
    if net_revenue <= 0:
        return None
    return ((net_revenue - cost_of_goods) / net_revenue * 100).quantize(Decimal("0.1"))


def is_late_shipment(status: SaleStatus, delivery_type: DeliveryType, sale_date: date | None, today: date) -> bool:
    return (
        status is SaleStatus.CONFIRMED
        and delivery_type is DeliveryType.SHIPPING
        and sale_date is not None
        and (today - sale_date).days > LATE_SHIPPING_DAYS
    )


@dataclass(frozen=True, slots=True)
class ShipmentInput:
    tracking_code: str
    actual_freight_cost: Decimal | None
    carrier: str | None = None


def validate_shipment(data: ShipmentInput, delivery_type: DeliveryType) -> ShipmentInput:
    """RN-27: a shipment needs tracking and its real freight cost (zero for free shipping)."""
    if delivery_type is not DeliveryType.SHIPPING:
        raise BusinessRuleError("Só pedidos com envio são expedidos. Registre a entrega diretamente.")
    tracking = clean_text(data.tracking_code)
    if not tracking:
        raise BusinessRuleError("Informe o código de rastreio.")
    if data.actual_freight_cost is None or data.actual_freight_cost < 0:
        raise BusinessRuleError("Informe o custo real do frete (zero se for grátis).")
    return replace(data, tracking_code=tracking.upper(), carrier=clean_text(data.carrier))
