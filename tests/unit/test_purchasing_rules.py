from datetime import date
from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.inventory import StockItemKind
from domain.partners import SupplyType
from domain.purchasing import (
    PurchaseInput,
    PurchaseItemInput,
    allocate_freight,
    effective_unit_cost,
    validate_purchase,
)

ORDER_DATE = date(2026, 11, 22)
COFFEE = PurchaseItemInput(StockItemKind.GREEN_COFFEE, 1, Decimal("30"), Decimal("60"))


def test_freight_goes_into_effective_cost():
    [freight] = allocate_freight([Decimal("1800.00")], Decimal("90.00"))
    assert effective_unit_cost(Decimal("30"), Decimal("60"), freight) == Decimal("63.0000")


def test_freight_rounding_remainder_stays_on_last_item():
    shares = allocate_freight([Decimal("100.00"), Decimal("100.00"), Decimal("100.00")], Decimal("10.00"))
    assert shares == [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")]
    assert sum(shares) == Decimal("10.00")


def test_service_supplier_has_no_purchase_order():
    with pytest.raises(BusinessRuleError, match="serviço"):
        validate_purchase(PurchaseInput(1, (COFFEE,)), SupplyType.SERVICE, ORDER_DATE)


def test_packaging_supplier_cannot_sell_coffee():
    with pytest.raises(BusinessRuleError, match="não vende"):
        validate_purchase(PurchaseInput(1, (COFFEE,)), SupplyType.PACKAGING, ORDER_DATE)


@pytest.mark.parametrize(
    "changes",
    [
        {"items": ()},
        {"items": (COFFEE, COFFEE)},
        {"installments": 7},
        {"freight_amount": Decimal("-1")},
        {"expected_date": date(2026, 11, 1)},
        {"supplier_id": None},
    ],
)
def test_invalid_purchase_is_rejected(changes):
    data = PurchaseInput(**({"supplier_id": 1, "items": (COFFEE,)} | changes))
    with pytest.raises(BusinessRuleError):
        validate_purchase(data, SupplyType.GREEN_COFFEE, ORDER_DATE)


def test_packaging_quantity_must_be_whole():
    bag = PurchaseItemInput(StockItemKind.PACKAGING_ITEM, 1, Decimal("10.5"), Decimal("1.8"))
    with pytest.raises(BusinessRuleError, match="inteiras"):
        validate_purchase(PurchaseInput(1, (bag,)), SupplyType.PACKAGING, ORDER_DATE)
