from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.inventory import (
    AdjustmentReason,
    MovementType,
    StockBalance,
    StockItemKind,
    StockItemRef,
    adjustment_quantity,
    plan_movement,
    reverse_weighted_average_cost,
    weighted_average_cost,
)


def balance(kind=StockItemKind.GREEN_COFFEE, stock="20", cost="60", label="BVCAT · Boa Vista") -> StockBalance:
    return StockBalance(StockItemRef(kind, 1), label, Decimal(stock), Decimal(cost))


def test_weighted_average_cost_matches_spec_example():
    assert weighted_average_cost(Decimal("20"), Decimal("60"), Decimal("20"), Decimal("66")) == Decimal("63.0000")


def test_reverse_weighted_average_cost_undoes_entry():
    assert reverse_weighted_average_cost(Decimal("40"), Decimal("63"), Decimal("20"), Decimal("66")) == Decimal(
        "60.0000"
    )


def test_reverse_weighted_average_keeps_cost_when_stock_empties():
    assert reverse_weighted_average_cost(Decimal("20"), Decimal("63"), Decimal("20"), Decimal("66")) == Decimal("63")


def test_entry_recalculates_average_cost():
    plan = plan_movement(balance(), MovementType.PURCHASE_IN, Decimal("20"), Decimal("66"))
    assert plan.new_stock == Decimal("40.000")
    assert plan.new_unit_cost == Decimal("63.0000")


def test_exit_keeps_average_cost_and_uses_it():
    plan = plan_movement(balance(), MovementType.ROAST_OUT, Decimal("-10"))
    assert (plan.new_stock, plan.unit_cost, plan.new_unit_cost) == (Decimal("10.000"), Decimal("60"), Decimal("60"))


def test_insufficient_stock_message_names_item_and_quantities():
    product = balance(StockItemKind.PRODUCT, "17", "20.0071", "CC-BVCAT-MED-GR-250")
    with pytest.raises(BusinessRuleError) as error:
        plan_movement(product, MovementType.SALE_OUT, Decimal("-30"))
    assert str(error.value) == "Estoque insuficiente: CC-BVCAT-MED-GR-250 tem 17 un., você pediu 30 un."


def test_units_must_be_whole():
    with pytest.raises(BusinessRuleError, match="inteiras"):
        plan_movement(balance(StockItemKind.PACKAGING_ITEM), MovementType.PURCHASE_IN, Decimal("1.5"), Decimal("1"))


@pytest.mark.parametrize(
    ("movement_type", "quantity"), [(MovementType.PURCHASE_IN, "-1"), (MovementType.SALE_OUT, "1")]
)
def test_movement_sign_must_match_type(movement_type, quantity):
    with pytest.raises(BusinessRuleError):
        plan_movement(balance(), movement_type, Decimal(quantity), Decimal("1"))


def test_roast_batch_keeps_its_fixed_cost():
    batch = balance(StockItemKind.ROAST_BATCH, "0", "71.4286", "T-20261122-01")
    plan = plan_movement(batch, MovementType.ROAST_IN, Decimal("8.4"))
    assert (plan.unit_cost, plan.new_unit_cost) == (Decimal("71.4286"), Decimal("71.4286"))


def test_opening_adjustment_requires_unit_cost():
    with pytest.raises(BusinessRuleError, match="custo"):
        plan_movement(balance(), MovementType.INVENTORY_ADJUSTMENT, Decimal("5"), reason=AdjustmentReason.OPENING)


def test_count_adjustment_returns_difference():
    assert adjustment_quantity(AdjustmentReason.COUNT, Decimal("20"), counted_stock=Decimal("18.5")) == Decimal("-1.5")


def test_loss_adjustment_is_negative():
    assert adjustment_quantity(AdjustmentReason.TASTING, Decimal("17"), lost_quantity=Decimal("1")) == Decimal("-1")


def test_count_equal_to_stock_is_rejected():
    with pytest.raises(BusinessRuleError, match="igual"):
        adjustment_quantity(AdjustmentReason.COUNT, Decimal("20"), counted_stock=Decimal("20"))
