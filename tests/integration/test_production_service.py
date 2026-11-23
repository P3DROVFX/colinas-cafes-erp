from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from core.clock import today
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.catalog import RoastProfile
from domain.dates import add_months
from domain.inventory import AdjustmentReason, MovementType, StockItemKind, StockItemRef
from domain.production import HarvestInput, PackingInput, RoastBatchStatus, RoastInput
from domain.purchasing import PurchaseStatus
from services import catalog as catalog_service
from services import integrity as integrity_service
from services import inventory as inventory_service
from services import production as production_service
from services import purchases as purchases_service
from services.inventory import AdjustmentInput
from services.production import PeriodFilters
from services.purchases import PurchaseFilters
from tests.integration.demo_catalog import build_demo_catalog, create_own_coffee, demo_product

TODAY_CODE = f"{today():%Y%m%d}"


@pytest.fixture
def manager(make_user):
    return make_user(Role.MANAGER)


@pytest.fixture
def catalog(manager):
    catalog = build_demo_catalog(manager)
    for data in (catalog.coffee_purchase(), catalog.packaging_purchase()):
        purchases_service.create_purchase(manager, data)
    pending = PurchaseFilters(today(), today(), None, (PurchaseStatus.PENDING,))
    for purchase in purchases_service.list_purchases(manager, pending):
        purchases_service.receive_purchase(manager, purchase["id"])
    return catalog


def roast_input(catalog, green="10", roasted="8.4", **changes) -> RoastInput:
    values = {
        "green_coffee_id": catalog.coffee_id,
        "roast_profile": RoastProfile.MEDIUM,
        "green_weight_kg": Decimal(green),
        "roasted_weight_kg": Decimal(roasted),
    }
    return RoastInput(**(values | changes))


def balance(manager, kind: StockItemKind, item_id: int):
    return inventory_service.get_stock_balance(manager, StockItemRef(kind, item_id))


def batch_id_by_code(manager, code: str) -> int:
    filters = PeriodFilters(today() - timedelta(days=60), today())
    return next(
        row["id"]
        for row in production_service.list_roast_batches(manager, filters, tuple(RoastBatchStatus))
        if row["code"] == code
    )


def table_counts(database_url) -> dict[str, int]:
    tables = ("roast_batches", "packing_batches", "stock_movements", "financial_entries", "harvests")
    with psycopg.connect(database_url) as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}


def test_demo_steps_4_and_5_roast_and_pack(manager, catalog):
    roasted = production_service.roast(manager, roast_input(catalog))
    assert roasted.code == f"T-{TODAY_CODE}-01"
    assert roasted.weight_loss_pct == Decimal("16.00")
    assert roasted.cost_per_kg == Decimal("71.4286")
    assert [(change.before, change.after) for change in roasted.effects.stock] == [
        (Decimal("30.000"), Decimal("20.000")),
        (Decimal("0"), Decimal("8.400")),
    ]
    batch_id = batch_id_by_code(manager, roasted.code)
    detail = production_service.get_roast_batch_detail(manager, batch_id)
    assert [row["movement_type"] for row in detail.movements] == [MovementType.ROAST_IN]

    packed = production_service.pack(manager, PackingInput(catalog.product_id, batch_id, 20))
    assert packed.code == f"E-{TODAY_CODE}-01"
    assert packed.unit_cost == Decimal("20.0071")
    assert packed.expiry_date == add_months(today(), 12)
    assert not packed.batch_closed

    assert balance(manager, StockItemKind.ROAST_BATCH, batch_id).stock == Decimal("3.400")
    assert balance(manager, StockItemKind.PACKAGING_ITEM, catalog.bag_id).stock == Decimal("80")
    assert balance(manager, StockItemKind.PACKAGING_ITEM, catalog.label_id).stock == Decimal("80")
    product = balance(manager, StockItemKind.PRODUCT, catalog.product_id)
    assert (product.stock, product.unit_cost) == (Decimal("20"), Decimal("20.0071"))
    [packing] = production_service.get_roast_batch_detail(manager, batch_id).packings
    assert packing["days_since_roast"] == 0
    assert all(result.passed for result in integrity_service.run_integrity_checks(manager))


@pytest.mark.parametrize(
    ("green", "roasted", "message"),
    [("18", "15", "capacidade do torrador"), ("10", "6", "40,00%"), ("10", "7", "Confirme")],
)
def test_roast_limits_block_and_record_nothing(manager, catalog, database_url, green, roasted, message):
    before = table_counts(database_url)
    with pytest.raises(BusinessRuleError, match=message):
        production_service.roast(manager, roast_input(catalog, green, roasted))
    assert table_counts(database_url) == before


def test_confirmed_unusual_weight_loss_is_accepted(manager, catalog):
    result = production_service.roast(manager, roast_input(catalog, "10", "7", unusual_loss_confirmed=True))
    assert result.weight_loss_pct == Decimal("30.00")


def test_roast_without_enough_green_coffee_rolls_back(manager, catalog, database_url):
    production_service.roast(manager, roast_input(catalog, "15", "12.6"))
    production_service.roast(manager, roast_input(catalog, "15", "12.6"))
    before = table_counts(database_url)
    with pytest.raises(BusinessRuleError, match="Estoque insuficiente: BVCAT · Boa Vista Catuaí Amarelo tem 0,000 kg"):
        production_service.roast(manager, roast_input(catalog))
    assert table_counts(database_url) == before


def test_packing_refuses_batch_of_another_profile(manager, catalog):
    dark_product = catalog_service.create_product(
        manager, demo_product(catalog.coffee_id, catalog.bag_id, catalog.label_id, RoastProfile.DARK)
    )
    batch_id = batch_id_by_code(manager, production_service.roast(manager, roast_input(catalog)).code)
    assert production_service.list_compatible_batches(manager, dark_product) == []
    with pytest.raises(BusinessRuleError, match="mesmo café e perfil"):
        production_service.pack(manager, PackingInput(dark_product, batch_id, 1))


def test_packing_shortage_says_what_is_missing_and_records_nothing(manager, catalog, database_url):
    batch_id = batch_id_by_code(manager, production_service.roast(manager, roast_input(catalog)).code)
    before = table_counts(database_url)
    with pytest.raises(BusinessRuleError, match=r"tem 8,400 kg e precisa de 10,000 kg"):
        production_service.pack(manager, PackingInput(catalog.product_id, batch_id, 40))
    assert table_counts(database_url) == before


def test_packing_the_whole_batch_closes_it(manager, catalog):
    batch_id = batch_id_by_code(manager, production_service.roast(manager, roast_input(catalog, "10", "8.5")).code)
    result = production_service.pack(manager, PackingInput(catalog.product_id, batch_id, 34))
    assert result.batch_closed
    detail = production_service.get_roast_batch_detail(manager, batch_id)
    assert detail.batch["status"] == RoastBatchStatus.CLOSED
    with pytest.raises(BusinessRuleError, match="encerrado"):
        production_service.pack(manager, PackingInput(catalog.product_id, batch_id, 1))


def test_closing_batch_writes_residue_off_as_loss(manager, catalog):
    batch_id = batch_id_by_code(manager, production_service.roast(manager, roast_input(catalog)).code)
    with pytest.raises(BusinessRuleError, match="o bastante para pacotes de 250 g"):
        production_service.close_roast_batch(manager, batch_id, "Fim do dia")
    production_service.pack(manager, PackingInput(catalog.product_id, batch_id, 33))

    effects = production_service.close_roast_batch(manager, batch_id, "Sobra menor que um pacote")
    assert [(change.before, change.after) for change in effects.stock] == [(Decimal("0.150"), Decimal("0.000"))]
    detail = production_service.get_roast_batch_detail(manager, batch_id)
    assert detail.batch["status"] == RoastBatchStatus.CLOSED
    assert detail.movements[0]["reason"] == AdjustmentReason.LOSS
    assert all(result.passed for result in integrity_service.run_integrity_checks(manager))


def test_adjusting_batch_to_zero_closes_it_and_closed_batch_refuses_adjustments(manager, catalog):
    batch_id = batch_id_by_code(manager, production_service.roast(manager, roast_input(catalog)).code)
    batch = StockItemRef(StockItemKind.ROAST_BATCH, batch_id)
    inventory_service.adjust_inventory(
        manager, AdjustmentInput(batch, AdjustmentReason.DAMAGE, "Lote queimado", lost_quantity=Decimal("8.4"))
    )
    assert production_service.get_roast_batch_detail(manager, batch_id).batch["status"] == RoastBatchStatus.CLOSED
    with pytest.raises(BusinessRuleError, match="encerrado e não recebe ajustes"):
        inventory_service.adjust_inventory(
            manager, AdjustmentInput(batch, AdjustmentReason.COUNT, "Recontagem", counted_stock=Decimal("1"))
        )


def test_harvest_adds_own_coffee_at_cost_and_creates_payable(manager, catalog):
    own_coffee_id = create_own_coffee(manager)
    result = production_service.register_harvest(
        manager, HarvestInput(own_coffee_id, Decimal("120"), Decimal("2400"), notes="Safra 2026, lote 1")
    )
    assert result.number.startswith(f"COL-{today().year}-")
    coffee = balance(manager, StockItemKind.GREEN_COFFEE, own_coffee_id)
    assert (coffee.stock, coffee.unit_cost) == (Decimal("120.000"), Decimal("20.0000"))
    [entry] = result.effects.entries
    assert (entry.amount, entry.due_date) == (Decimal("2400"), today() + timedelta(days=30))
    [row] = production_service.list_harvests(manager, PeriodFilters(today(), today()))
    assert (row["cost_per_kg"], row["entry_status"]) == (Decimal("20.0000"), "PENDING")
    assert all(result.passed for result in integrity_service.run_integrity_checks(manager))


def test_harvest_refuses_partner_coffee(manager, catalog, database_url):
    before = table_counts(database_url)
    with pytest.raises(BusinessRuleError, match="fazenda própria"):
        production_service.register_harvest(manager, HarvestInput(catalog.coffee_id, Decimal("10"), Decimal("100")))
    assert table_counts(database_url) == before


def test_production_role_runs_operations_and_viewer_only_reads(make_user, manager, catalog):
    production = make_user(Role.PRODUCTION)
    production_service.roast(production, roast_input(catalog))
    viewer = make_user(Role.VIEWER)
    assert production_service.list_roast_batches(viewer, PeriodFilters(today(), today()), (RoastBatchStatus.OPEN,))
    with pytest.raises(AccessDeniedError):
        production_service.roast(viewer, roast_input(catalog))
    with pytest.raises(AccessDeniedError):
        production_service.list_roast_batches(make_user(Role.SALES), PeriodFilters(today(), today()), ())


def test_stale_batches_are_listed_for_freshness_alert(manager, catalog, database_url):
    code = production_service.roast(manager, roast_input(catalog)).code
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE roast_batches SET roast_date = roast_date - 20 WHERE code = %s", (code,))
    alert_days, stale = production_service.list_stale_roast_batches(manager)
    assert alert_days == 15
    assert [(row["code"], row["days_since_roast"]) for row in stale] == [(code, 20)]
