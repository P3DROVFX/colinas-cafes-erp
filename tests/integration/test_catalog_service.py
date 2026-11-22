from dataclasses import replace
from decimal import Decimal

import psycopg
import pytest

from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.brazil import PersonType
from domain.catalog import (
    FarmInput,
    GreenCoffeeInput,
    Grind,
    PackagingItemInput,
    PackagingKind,
    Process,
    ProductInput,
    RoastProfile,
)
from domain.partners import SupplierInput, SupplyType
from services import catalog as catalog_service
from services import partners as partners_service
from services.master_data import RecordInUseError


@pytest.fixture
def manager(make_user):
    return make_user(Role.MANAGER)


@pytest.fixture
def catalog(manager):
    supplier_id = partners_service.create_supplier(
        manager,
        SupplierInput("José da Boa Vista", PersonType.INDIVIDUAL, "529.982.247-25", SupplyType.GREEN_COFFEE),
    )
    farm_id = catalog_service.create_farm(
        manager, FarmInput("Sítio Boa Vista", "Taquaritinga do Norte", "PE", "José", False, supplier_id, 950)
    )
    coffee = GreenCoffeeInput("BVCAT", "Boa Vista Catuaí", farm_id, "Catuaí Amarelo", Process.NATURAL, 2026)
    coffee_id = catalog_service.create_green_coffee(manager, coffee)
    bag_id = catalog_service.create_packaging_item(manager, PackagingItemInput("Pacote 250 g", PackagingKind.BAG, 250))
    bag_500_id = catalog_service.create_packaging_item(
        manager, PackagingItemInput("Pacote 500 g", PackagingKind.BAG, 500)
    )
    label_id = catalog_service.create_packaging_item(manager, PackagingItemInput("Etiqueta", PackagingKind.LABEL))
    product = ProductInput(
        "Boa Vista Catuaí 250 g",
        coffee_id,
        RoastProfile.MEDIUM,
        Grind.WHOLE_BEAN,
        250,
        bag_id,
        label_id,
        Decimal("42.00"),
        Decimal("45.00"),
    )
    product_id = catalog_service.create_product(manager, product)
    return {
        "supplier_id": supplier_id,
        "farm_id": farm_id,
        "coffee": coffee,
        "coffee_id": coffee_id,
        "bag_id": bag_id,
        "bag_500_id": bag_500_id,
        "label_id": label_id,
        "product": product,
        "product_id": product_id,
    }


def test_product_gets_sku_from_coffee_code(manager, catalog):
    [product] = catalog_service.list_products(manager)
    assert product["sku"] == "CC-BVCAT-MED-GR-250"
    assert product["stock"] == 0
    assert product["avg_unit_cost"] == 0


def test_product_bag_must_match_weight(manager, catalog):
    product = replace(catalog["product"], roast_profile=RoastProfile.DARK, bag_id=catalog["bag_500_id"])
    with pytest.raises(BusinessRuleError, match="não serve"):
        catalog_service.create_product(manager, product)


def test_duplicate_product_combination_is_rejected(manager, catalog):
    with pytest.raises(BusinessRuleError, match="Já existe um produto"):
        catalog_service.create_product(manager, replace(catalog["product"], name="Outro nome"))


def test_partner_farm_needs_green_coffee_supplier(manager):
    supplier_id = partners_service.create_supplier(
        manager, SupplierInput("Embalagens PE", PersonType.COMPANY, "11.222.333/0001-81", SupplyType.PACKAGING)
    )
    with pytest.raises(BusinessRuleError, match="café verde"):
        catalog_service.create_farm(manager, FarmInput("Sítio X", "Garanhuns", "PE", "Ana", False, supplier_id))


def test_duplicate_farm_name_is_a_business_error(manager, catalog):
    with pytest.raises(BusinessRuleError, match="Já existe uma fazenda"):
        catalog_service.create_farm(manager, FarmInput("Sítio Boa Vista", "Garanhuns", "PE", "Ana", True))


def test_green_coffee_identity_cannot_change(manager, catalog):
    with pytest.raises(BusinessRuleError, match="não podem mudar"):
        catalog_service.update_green_coffee(
            manager, catalog["coffee_id"], replace(catalog["coffee"], harvest_year=2025)
        )


def test_green_coffee_descriptive_fields_can_change(manager, catalog):
    changed = replace(catalog["coffee"], name="Catuaí da Boa Vista", sca_score=Decimal("86.5"))
    catalog_service.update_green_coffee(manager, catalog["coffee_id"], changed)
    [coffee] = catalog_service.list_green_coffees(manager)
    assert coffee["name"] == "Catuaí da Boa Vista"
    assert coffee["sca_score"] == Decimal("86.50")


def test_unused_record_is_deleted(manager, catalog):
    catalog_service.delete_packaging_item(manager, catalog["bag_500_id"])
    names = [item["name"] for item in catalog_service.list_packaging_items(manager, include_inactive=True)]
    assert "Pacote 500 g" not in names


def test_referenced_record_can_only_be_deactivated(manager, catalog):
    with pytest.raises(RecordInUseError):
        catalog_service.delete_packaging_item(manager, catalog["bag_id"])
    catalog_service.set_packaging_item_active(manager, catalog["bag_id"], False)
    options = catalog_service.list_packaging_options(manager, PackagingKind.BAG)
    assert catalog["bag_id"] not in [option["id"] for option in options]
    assert catalog["bag_id"] in [item["id"] for item in catalog_service.list_packaging_items(manager, "", True)]


def test_packaging_in_use_keeps_kind_and_capacity(manager, catalog):
    with pytest.raises(BusinessRuleError, match="não podem mudar"):
        catalog_service.update_packaging_item(
            manager, catalog["bag_id"], PackagingItemInput("Pacote 250 g", PackagingKind.BAG, 500)
        )


def test_default_shipping_box_cannot_be_deleted(manager, database_url):
    box_id = catalog_service.create_packaging_item(
        manager, PackagingItemInput("Caixa 2 kg", PackagingKind.SHIPPING_BOX, 2000)
    )
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE settings SET value = %s WHERE key = 'default_shipping_box_id'", (str(box_id),))
    with pytest.raises(BusinessRuleError, match="caixa de envio padrão"):
        catalog_service.delete_packaging_item(manager, box_id)


def test_production_edits_product_but_not_prices(make_user, catalog):
    production = make_user(Role.PRODUCTION)
    catalog_service.update_product(production, catalog["product_id"], replace(catalog["product"], min_stock=10))
    with pytest.raises(AccessDeniedError):
        catalog_service.update_product(
            production, catalog["product_id"], replace(catalog["product"], price_local=Decimal("40.00"))
        )
    with pytest.raises(AccessDeniedError):
        catalog_service.create_product(production, replace(catalog["product"], grind=Grind.FILTER))


def test_viewer_cannot_write_catalog(make_user):
    viewer = make_user(Role.VIEWER)
    with pytest.raises(AccessDeniedError):
        catalog_service.create_farm(viewer, FarmInput("Colinas", "Garanhuns", "PE", "Família Lima", True))


def test_search_matches_name_and_farm(manager, catalog):
    assert len(catalog_service.list_green_coffees(manager, "boa vista")) == 1
    assert catalog_service.list_green_coffees(manager, "bourbon") == []
