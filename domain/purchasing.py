from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.fields import clean_text, ensure_between, ensure_not_negative
from domain.inventory import StockItemKind, is_whole_unit
from domain.numbers import round_money, round_unit_cost
from domain.partners import SupplyType

MAX_INSTALLMENTS = 6
MAX_FIRST_DUE_DAYS = 365

SUPPLY_ITEM_KINDS: dict[SupplyType, StockItemKind] = {
    SupplyType.GREEN_COFFEE: StockItemKind.GREEN_COFFEE,
    SupplyType.PACKAGING: StockItemKind.PACKAGING_ITEM,
}


class PurchaseStatus(StrEnum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"


@dataclass(frozen=True, slots=True)
class PurchaseItemInput:
    kind: StockItemKind
    item_id: int
    quantity: Decimal
    unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class PurchaseInput:
    supplier_id: int | None
    items: tuple[PurchaseItemInput, ...]
    freight_amount: Decimal = Decimal("0")
    installments: int = 1
    first_due_days: int = 30
    expected_date: date | None = None
    supplier_invoice: str | None = None
    notes: str | None = None


def item_kind_for_supplier(supply_type: SupplyType) -> StockItemKind:
    if supply_type not in SUPPLY_ITEM_KINDS:
        raise BusinessRuleError("Fornecedores de serviço não têm pedido de compra. Lance a despesa no financeiro.")
    return SUPPLY_ITEM_KINDS[supply_type]


def _validate_item(item: PurchaseItemInput, expected_kind: StockItemKind) -> None:
    if item.kind is not expected_kind:
        raise BusinessRuleError(
            "Este fornecedor não vende esse tipo de item. Café e embalagens vão em pedidos separados."
        )
    if item.quantity <= 0 or item.unit_cost <= 0:
        raise BusinessRuleError("Cada item precisa de quantidade e custo unitário maiores que zero.")
    if is_whole_unit(item.kind) and item.quantity != item.quantity.to_integral_value():
        raise BusinessRuleError("Embalagens são compradas em unidades inteiras.")


def validate_purchase(data: PurchaseInput, supply_type: SupplyType, order_date: date) -> PurchaseInput:
    if data.supplier_id is None:
        raise BusinessRuleError("Selecione o fornecedor.")
    if not data.items:
        raise BusinessRuleError("Inclua pelo menos um item no pedido.")
    expected_kind = item_kind_for_supplier(supply_type)
    for item in data.items:
        _validate_item(item, expected_kind)
    if len({item.item_id for item in data.items}) != len(data.items):
        raise BusinessRuleError("Há itens repetidos no pedido. Junte as quantidades em uma linha.")
    ensure_not_negative(data.freight_amount, "O frete não pode ser negativo.")
    ensure_between(
        data.installments, 1, MAX_INSTALLMENTS, f"O número de parcelas deve ficar entre 1 e {MAX_INSTALLMENTS}."
    )
    ensure_between(
        data.first_due_days, 0, MAX_FIRST_DUE_DAYS, "O prazo da primeira parcela deve ficar entre 0 e 365 dias."
    )
    if data.expected_date is not None and data.expected_date < order_date:
        raise BusinessRuleError("A data prevista de entrega não pode ser anterior à data do pedido.")
    return replace(
        data,
        freight_amount=round_money(data.freight_amount),
        supplier_invoice=clean_text(data.supplier_invoice),
        notes=clean_text(data.notes),
    )


def line_amount(quantity: Decimal, unit_cost: Decimal) -> Decimal:
    return round_money(quantity * unit_cost)


def products_amount(items: tuple[PurchaseItemInput, ...]) -> Decimal:
    return sum((line_amount(item.quantity, item.unit_cost) for item in items), Decimal("0"))


def allocate_freight(line_amounts: list[Decimal], freight: Decimal) -> list[Decimal]:
    total = sum(line_amounts, Decimal("0"))
    if freight == 0 or total == 0:
        return [Decimal("0.00")] * len(line_amounts)
    shares = [round_money(freight * amount / total) for amount in line_amounts[:-1]]
    return [*shares, freight - sum(shares, Decimal("0"))]


def effective_unit_cost(quantity: Decimal, unit_cost: Decimal, allocated_freight: Decimal) -> Decimal:
    return round_unit_cost(unit_cost + allocated_freight / quantity)


def can_edit(status: PurchaseStatus) -> bool:
    return status is PurchaseStatus.PENDING
