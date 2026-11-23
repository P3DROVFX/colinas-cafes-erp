from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.catalog import RoastProfile
from domain.inventory import StockBalance, StockItemKind, StockItemRef
from domain.production import (
    HarvestInput,
    PackingBatchSource,
    PackingProduct,
    RoastBatchStatus,
    RoastInput,
    RoastLimits,
    add_months,
    can_close_batch,
    daily_code,
    describe_shortages,
    ensure_batch_fits_product,
    find_shortages,
    harvest_unit_cost,
    is_unusual_weight_loss,
    packed_coffee_unit_cost,
    packing_consumed_kg,
    roasted_cost_per_kg,
    validate_harvest,
    validate_roast,
    weight_loss_pct,
)

LIMITS = RoastLimits(
    min_green_kg=Decimal("1"),
    capacity_kg=Decimal("15"),
    warn_min_pct=Decimal("10"),
    warn_max_pct=Decimal("25"),
    block_min_pct=Decimal("5"),
    block_max_pct=Decimal("35"),
)
ROAST_DAY = date(2026, 11, 23)


def roast_input(green: str, roasted: str, confirmed: bool = False) -> RoastInput:
    return RoastInput(1, RoastProfile.MEDIUM, Decimal(green), Decimal(roasted), unusual_loss_confirmed=confirmed)


def test_weight_loss_matches_spec_example():
    assert weight_loss_pct(Decimal("10"), Decimal("8.4")) == Decimal("16.00")


def test_roasted_cost_absorbs_weight_loss():
    assert roasted_cost_per_kg(Decimal("10"), Decimal("60"), Decimal("8.4")) == Decimal("71.4286")


def test_valid_roast_passes():
    assert validate_roast(roast_input("10", "8.4"), LIMITS).green_weight_kg == Decimal("10.000")


@pytest.mark.parametrize(("green", "roasted"), [("18", "15"), ("0.5", "0.4")])
def test_roast_outside_roaster_capacity_is_blocked(green, roasted):
    with pytest.raises(BusinessRuleError, match="capacidade do torrador"):
        validate_roast(roast_input(green, roasted), LIMITS)


@pytest.mark.parametrize("roasted", ["10", "11", "0"])
def test_roasted_weight_must_be_below_green_weight(roasted):
    with pytest.raises(BusinessRuleError, match="peso torrado"):
        validate_roast(roast_input("10", roasted), LIMITS)


def test_weight_loss_outside_physical_range_is_blocked_even_when_confirmed():
    with pytest.raises(BusinessRuleError, match="40,00%"):
        validate_roast(roast_input("10", "6", confirmed=True), LIMITS)


def test_unusual_weight_loss_needs_confirmation():
    with pytest.raises(BusinessRuleError, match="Confirme"):
        validate_roast(roast_input("10", "7"), LIMITS)
    assert validate_roast(roast_input("10", "7", confirmed=True), LIMITS)


@pytest.mark.parametrize(("loss", "unusual"), [("9.99", True), ("10", False), ("25", False), ("25.01", True)])
def test_unusual_weight_loss_band(loss, unusual):
    assert is_unusual_weight_loss(Decimal(loss), LIMITS) is unusual


def test_harvest_cost_per_kg_and_default_due_date():
    data = validate_harvest(HarvestInput(1, Decimal("120"), Decimal("2400")), ROAST_DAY)
    assert data.due_date == ROAST_DAY + timedelta(days=30)
    assert harvest_unit_cost(data.total_cost, data.quantity_kg) == Decimal("20.0000")


@pytest.mark.parametrize(
    ("quantity", "cost", "message"),
    [("0", "100", "quantidade"), ("10", "0", "custo total")],
)
def test_harvest_requires_quantity_and_cost(quantity, cost, message):
    with pytest.raises(BusinessRuleError, match=message):
        validate_harvest(HarvestInput(1, Decimal(quantity), Decimal(cost)), ROAST_DAY)


def test_harvest_due_date_cannot_precede_harvest():
    with pytest.raises(BusinessRuleError, match="vencimento"):
        validate_harvest(
            HarvestInput(1, Decimal("10"), Decimal("100"), due_date=ROAST_DAY - timedelta(days=1)), ROAST_DAY
        )


def test_daily_codes_are_zero_padded():
    assert daily_code("T", ROAST_DAY, 1) == "T-20261123-01"


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [(date(2026, 11, 23), 12, date(2027, 11, 23)), (date(2026, 1, 31), 1, date(2026, 2, 28))],
)
def test_add_months_clamps_to_month_end(start, months, expected):
    assert add_months(start, months) == expected


def test_packing_consumption_and_bag_cost_match_spec_example():
    assert packing_consumed_kg(20, 250) == Decimal("5.000")
    coffee = packed_coffee_unit_cost(250, Decimal("10"), Decimal("60"), Decimal("8.4"))
    assert coffee == Decimal("17.8571")
    assert coffee + Decimal("1.80") + Decimal("0.35") == Decimal("20.0071")


BATCH = PackingBatchSource("T-20261123-01", RoastBatchStatus.OPEN, 1, RoastProfile.MEDIUM, ROAST_DAY)
PRODUCT = PackingProduct("CC-BVCAT-MED-GR-250", 1, RoastProfile.MEDIUM, 250)


def test_compatible_batch_is_accepted():
    ensure_batch_fits_product(BATCH, PRODUCT, ROAST_DAY)


@pytest.mark.parametrize(
    ("product", "message"),
    [
        (PackingProduct("CC-BVCAT-ESC-GR-250", 1, RoastProfile.DARK, 250), "mesmo café e perfil"),
        (PackingProduct("CC-GESHA-MED-GR-250", 2, RoastProfile.MEDIUM, 250), "mesmo café e perfil"),
    ],
)
def test_incompatible_batch_is_refused(product, message):
    with pytest.raises(BusinessRuleError, match=message):
        ensure_batch_fits_product(BATCH, product, ROAST_DAY)


def test_closed_batch_and_packing_before_roast_are_refused():
    closed = PackingBatchSource("T-1", RoastBatchStatus.CLOSED, 1, RoastProfile.MEDIUM, ROAST_DAY)
    with pytest.raises(BusinessRuleError, match="encerrado"):
        ensure_batch_fits_product(closed, PRODUCT, ROAST_DAY)
    with pytest.raises(BusinessRuleError, match="anterior à data da torra"):
        ensure_batch_fits_product(BATCH, PRODUCT, ROAST_DAY - timedelta(days=1))


def test_shortages_say_what_is_missing_and_how_much():
    batch = StockBalance(StockItemRef(StockItemKind.ROAST_BATCH, 1), "T-20261123-01", Decimal("3.4"), Decimal("71"))
    bag = StockBalance(StockItemRef(StockItemKind.PACKAGING_ITEM, 2), "Pacote", Decimal("80"), Decimal("1.8"))
    shortages = find_shortages([(batch, Decimal("5")), (bag, Decimal("20"))])
    assert [shortage.label for shortage in shortages] == ["T-20261123-01"]
    assert describe_shortages(shortages) == (
        "Falta material para o envase: T-20261123-01 tem 3,400 kg e precisa de 5,000 kg."
    )


@pytest.mark.parametrize(
    ("stock", "smallest_bag", "allowed"),
    [("0.2", 250, True), ("0.25", 250, False), ("3.4", 250, False), ("3.4", None, True)],
)
def test_batch_closes_only_with_residue_smaller_than_a_bag(stock, smallest_bag, allowed):
    assert can_close_batch(Decimal(stock), smallest_bag) is allowed
