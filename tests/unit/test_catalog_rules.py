from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.catalog import (
    FarmInput,
    GreenCoffeeInput,
    Grind,
    PackagingItemInput,
    PackagingKind,
    PackagingSpec,
    Process,
    ProductInput,
    RoastProfile,
    build_sku,
    validate_farm,
    validate_green_coffee,
    validate_packaging_item,
    validate_product,
)

BAG_250 = PackagingSpec("Pacote kraft 250 g", PackagingKind.BAG, 250)
LABEL = PackagingSpec("Etiqueta padrão", PackagingKind.LABEL, None)


def make_product(**changes) -> ProductInput:
    values = {
        "name": "Boa Vista Catuaí 250 g",
        "green_coffee_id": 1,
        "roast_profile": RoastProfile.MEDIUM,
        "grind": Grind.WHOLE_BEAN,
        "weight_g": 250,
        "bag_id": 1,
        "label_id": 2,
        "price_local": Decimal("42.00"),
        "price_online": Decimal("45.00"),
    }
    return ProductInput(**(values | changes))


def test_sku_follows_spec_pattern():
    assert build_sku("BVCAT", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 250) == "CC-BVCAT-MED-GR-250"


def test_own_farm_cannot_have_supplier():
    with pytest.raises(BusinessRuleError, match="própria"):
        validate_farm(FarmInput("Colinas", "Garanhuns", "PE", "Família Lima", is_own=True, supplier_id=3))


def test_partner_farm_requires_supplier():
    with pytest.raises(BusinessRuleError, match="parceira"):
        validate_farm(FarmInput("Boa Vista", "Taquaritinga do Norte", "PE", "José", is_own=False))


def test_green_coffee_code_is_uppercased():
    coffee = validate_green_coffee(
        GreenCoffeeInput("bvcat", "Boa Vista Catuaí", 1, "Catuaí Amarelo", Process.NATURAL, 2026)
    )
    assert coffee.code == "BVCAT"


@pytest.mark.parametrize("changes", [{"code": "BV CAT"}, {"sca_score": Decimal("59")}, {"harvest_year": 2019}])
def test_invalid_green_coffee_is_rejected(changes):
    values = {"code": "BVCAT", "name": "Boa Vista", "farm_id": 1, "variety": "Catuaí",
              "process": Process.NATURAL, "harvest_year": 2026}  # fmt: skip
    with pytest.raises(BusinessRuleError):
        validate_green_coffee(GreenCoffeeInput(**(values | changes)))


@pytest.mark.parametrize(
    ("kind", "capacity"),
    [(PackagingKind.BAG, 300), (PackagingKind.BAG, None), (PackagingKind.SHIPPING_BOX, 0)],
)
def test_packaging_capacity_must_match_kind(kind, capacity):
    with pytest.raises(BusinessRuleError):
        validate_packaging_item(PackagingItemInput("Embalagem", kind, capacity))


def test_label_capacity_is_cleared():
    assert validate_packaging_item(PackagingItemInput("Etiqueta", PackagingKind.LABEL, 250)).capacity_g is None


def test_product_bag_must_match_weight():
    bag_500 = PackagingSpec("Pacote kraft 500 g", PackagingKind.BAG, 500)
    with pytest.raises(BusinessRuleError, match="não serve"):
        validate_product(make_product(), bag_500, LABEL)


def test_product_label_must_be_a_label():
    with pytest.raises(BusinessRuleError, match="etiqueta"):
        validate_product(make_product(), BAG_250, BAG_250)


def test_product_prices_must_be_positive():
    with pytest.raises(BusinessRuleError):
        validate_product(make_product(price_wholesale=Decimal("0")), BAG_250, LABEL)


def test_valid_product_passes():
    assert validate_product(make_product(), BAG_250, LABEL).name == "Boa Vista Catuaí 250 g"
