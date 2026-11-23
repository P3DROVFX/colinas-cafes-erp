from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.numbers import format_decimal, round_kilograms, round_unit_cost


class StockItemKind(StrEnum):
    GREEN_COFFEE = "GREEN_COFFEE"
    ROAST_BATCH = "ROAST_BATCH"
    PACKAGING_ITEM = "PACKAGING_ITEM"
    PRODUCT = "PRODUCT"


class MovementType(StrEnum):
    PURCHASE_IN = "PURCHASE_IN"
    PURCHASE_REVERSAL = "PURCHASE_REVERSAL"
    HARVEST_IN = "HARVEST_IN"
    ROAST_OUT = "ROAST_OUT"
    ROAST_IN = "ROAST_IN"
    PACKING_OUT = "PACKING_OUT"
    PACKING_IN = "PACKING_IN"
    SALE_OUT = "SALE_OUT"
    SALE_REVERSAL = "SALE_REVERSAL"
    INVENTORY_ADJUSTMENT = "INVENTORY_ADJUSTMENT"


class AdjustmentReason(StrEnum):
    COUNT = "COUNT"
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"
    TASTING = "TASTING"
    EXPIRED = "EXPIRED"
    OPENING = "OPENING"


class SourceModule(StrEnum):
    PURCHASES = "PURCHASES"
    PRODUCTION = "PRODUCTION"
    SALES = "SALES"
    INVENTORY = "INVENTORY"
    MANUAL = "MANUAL"


INBOUND_TYPES = frozenset(
    {MovementType.PURCHASE_IN, MovementType.HARVEST_IN, MovementType.ROAST_IN, MovementType.PACKING_IN,
     MovementType.SALE_REVERSAL}
)  # fmt: skip
OUTBOUND_TYPES = frozenset(
    {MovementType.PURCHASE_REVERSAL, MovementType.ROAST_OUT, MovementType.PACKING_OUT, MovementType.SALE_OUT}
)
COST_ENTRY_TYPES = frozenset(
    {MovementType.PURCHASE_IN, MovementType.HARVEST_IN, MovementType.PACKING_IN, MovementType.SALE_REVERSAL}
)
COUNTED_REASONS = frozenset({AdjustmentReason.COUNT, AdjustmentReason.OPENING})
WHOLE_UNIT_KINDS = frozenset({StockItemKind.PACKAGING_ITEM, StockItemKind.PRODUCT})


@dataclass(frozen=True, slots=True)
class StockItemRef:
    kind: StockItemKind
    id: int


@dataclass(frozen=True, slots=True)
class StockBalance:
    item: StockItemRef
    label: str
    stock: Decimal
    unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class MovementPlan:
    quantity: Decimal
    unit_cost: Decimal
    new_stock: Decimal
    new_unit_cost: Decimal


def is_whole_unit(kind: StockItemKind) -> bool:
    return kind in WHOLE_UNIT_KINDS


def format_quantity(kind: StockItemKind, quantity: Decimal) -> str:
    if is_whole_unit(kind):
        return f"{format_decimal(quantity, 0)} un."
    return f"{format_decimal(quantity, 3)} kg"


def weighted_average_cost(stock: Decimal, average_cost: Decimal, quantity: Decimal, unit_cost: Decimal) -> Decimal:
    return round_unit_cost((stock * average_cost + quantity * unit_cost) / (stock + quantity))


def reverse_weighted_average_cost(
    stock: Decimal, average_cost: Decimal, quantity: Decimal, unit_cost: Decimal
) -> Decimal:
    remaining = stock - quantity
    if remaining == 0:
        return average_cost
    return max(round_unit_cost((stock * average_cost - quantity * unit_cost) / remaining), Decimal("0"))


def _ensure_sign(movement_type: MovementType, quantity: Decimal) -> None:
    if quantity == 0:
        raise BusinessRuleError("A quantidade do movimento não pode ser zero.")
    if movement_type in INBOUND_TYPES and quantity < 0:
        raise BusinessRuleError("Movimentos de entrada precisam de quantidade positiva.")
    if movement_type in OUTBOUND_TYPES and quantity > 0:
        raise BusinessRuleError("Movimentos de saída precisam de quantidade negativa.")


def _normalize_quantity(kind: StockItemKind, quantity: Decimal) -> Decimal:
    if is_whole_unit(kind):
        if quantity != quantity.to_integral_value():
            raise BusinessRuleError("Embalagens e produtos movimentam apenas unidades inteiras.")
        return quantity.to_integral_value()
    return round_kilograms(quantity)


def _required_unit_cost(unit_cost: Decimal | None) -> Decimal:
    if unit_cost is None or unit_cost < 0:
        raise BusinessRuleError("Informe o custo unitário da entrada.")
    return round_unit_cost(unit_cost)


def plan_movement(
    balance: StockBalance,
    movement_type: MovementType,
    quantity: Decimal,
    unit_cost: Decimal | None = None,
    reason: AdjustmentReason | None = None,
) -> MovementPlan:
    _ensure_sign(movement_type, quantity)
    if movement_type is MovementType.INVENTORY_ADJUSTMENT and reason is None:
        raise BusinessRuleError("Informe o motivo do ajuste.")
    kind = balance.item.kind
    quantity = _normalize_quantity(kind, quantity)
    new_stock = balance.stock + quantity
    if new_stock < 0:
        requested = format_quantity(kind, -quantity)
        raise BusinessRuleError(
            f"Estoque insuficiente: {balance.label} tem {format_quantity(kind, balance.stock)}, "
            f"você pediu {requested}{'' if requested.endswith('.') else '.'}"
        )
    if kind is StockItemKind.ROAST_BATCH:
        return MovementPlan(quantity, balance.unit_cost, new_stock, balance.unit_cost)
    is_opening = reason is AdjustmentReason.OPENING and quantity > 0
    if movement_type in COST_ENTRY_TYPES or is_opening:
        cost = _required_unit_cost(unit_cost)
        return MovementPlan(
            quantity, cost, new_stock, weighted_average_cost(balance.stock, balance.unit_cost, quantity, cost)
        )
    if movement_type is MovementType.PURCHASE_REVERSAL:
        cost = _required_unit_cost(unit_cost)
        new_cost = reverse_weighted_average_cost(balance.stock, balance.unit_cost, -quantity, cost)
        return MovementPlan(quantity, cost, new_stock, new_cost)
    return MovementPlan(quantity, balance.unit_cost, new_stock, balance.unit_cost)


def adjustment_quantity(
    reason: AdjustmentReason,
    current_stock: Decimal,
    counted_stock: Decimal | None = None,
    lost_quantity: Decimal | None = None,
) -> Decimal:
    if reason in COUNTED_REASONS:
        if counted_stock is None or counted_stock < 0:
            raise BusinessRuleError("Informe o saldo contado (zero ou mais).")
        if counted_stock == current_stock:
            raise BusinessRuleError("O saldo contado é igual ao saldo atual. Não há o que ajustar.")
        if reason is AdjustmentReason.OPENING and counted_stock < current_stock:
            raise BusinessRuleError("A implantação de saldo só aumenta o estoque. Use Contagem para reduzir.")
        return counted_stock - current_stock
    if lost_quantity is None or lost_quantity <= 0:
        raise BusinessRuleError("Informe a quantidade que saiu do estoque.")
    return -lost_quantity


class StockStatus(StrEnum):
    OK = "OK"
    BELOW_MINIMUM = "BELOW_MINIMUM"
    EMPTY = "EMPTY"


def stock_status(stock: Decimal, min_stock: Decimal | None) -> StockStatus:
    if stock <= 0:
        return StockStatus.EMPTY
    if min_stock is not None and stock < min_stock:
        return StockStatus.BELOW_MINIMUM
    return StockStatus.OK
