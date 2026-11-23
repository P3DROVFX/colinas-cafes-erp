from decimal import Decimal

import psycopg
import pytest

from core.clock import today
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.inventory import AdjustmentReason, StockItemKind, StockItemRef
from domain.purchasing import PurchaseStatus
from services import integrity as integrity_service
from services import inventory as inventory_service
from services import purchases as purchases_service
from services.inventory import AdjustmentInput
from services.purchases import PurchaseFilters
from tests.integration.demo_catalog import build_demo_catalog


@pytest.fixture
def manager(make_user):
    return make_user(Role.MANAGER)


@pytest.fixture
def catalog(manager):
    return build_demo_catalog(manager)


def coffee(catalog) -> StockItemRef:
    return StockItemRef(StockItemKind.GREEN_COFFEE, catalog.coffee_id)


def test_opening_balance_sets_stock_and_cost(manager, catalog):
    effects = inventory_service.adjust_inventory(
        manager,
        AdjustmentInput(
            coffee(catalog), AdjustmentReason.OPENING, "Carga inicial", Decimal("12.5"), unit_cost=Decimal("58")
        ),
    )
    [change] = effects.stock
    assert (change.before, change.after, change.unit_cost) == (Decimal("0"), Decimal("12.500"), Decimal("58.0000"))


def test_count_adjustment_moves_stock_to_counted_value(manager, catalog):
    inventory_service.adjust_inventory(
        manager,
        AdjustmentInput(coffee(catalog), AdjustmentReason.OPENING, "Carga", Decimal("20"), unit_cost=Decimal("60")),
    )
    effects = inventory_service.adjust_inventory(
        manager, AdjustmentInput(coffee(catalog), AdjustmentReason.COUNT, "Inventário mensal", Decimal("19.2"))
    )
    assert effects.stock[0].after == Decimal("19.200")
    movements = inventory_service.list_item_movements(manager, coffee(catalog), today(), today())
    assert [row["quantity"] for row in movements] == [Decimal("-0.800"), Decimal("20.000")]
    assert movements[0]["unit_cost"] == Decimal("60.0000")


def test_loss_larger_than_stock_is_rejected_without_changes(manager, catalog):
    with pytest.raises(BusinessRuleError, match="Estoque insuficiente"):
        inventory_service.adjust_inventory(
            manager,
            AdjustmentInput(coffee(catalog), AdjustmentReason.DAMAGE, "Saca rasgada", lost_quantity=Decimal("1")),
        )
    assert inventory_service.list_item_movements(manager, coffee(catalog), today(), today()) == []


def test_adjustment_requires_notes_and_manager(make_user, manager, catalog):
    data = AdjustmentInput(coffee(catalog), AdjustmentReason.COUNT, "", Decimal("1"))
    with pytest.raises(BusinessRuleError, match="observação"):
        inventory_service.adjust_inventory(manager, data)
    with pytest.raises(AccessDeniedError):
        inventory_service.adjust_inventory(make_user(Role.PRODUCTION), data)


def test_database_rejects_negative_stock(database_url, catalog):
    with psycopg.connect(database_url) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("UPDATE green_coffees SET stock_kg = -1 WHERE id = %s", (catalog.coffee_id,))


def test_integrity_checks_pass_after_operations_and_catch_divergence(manager, catalog, database_url):
    number = purchases_service.create_purchase(manager, catalog.packaging_purchase())
    filters = PurchaseFilters(today(), today(), None, tuple(PurchaseStatus))
    [purchase] = [row for row in purchases_service.list_purchases(manager, filters) if row["number"] == number]
    purchases_service.receive_purchase(manager, purchase["id"])
    assert all(result.passed for result in integrity_service.run_integrity_checks(manager))

    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE packaging_items SET stock = stock + 1 WHERE id = %s", (catalog.bag_id,))
        connection.execute("DELETE FROM financial_entries WHERE source_module = 'PURCHASES'")
    failed = {result.code for result in integrity_service.run_integrity_checks(manager) if not result.passed}
    assert failed == {"I1", "I2", "I5"}


def test_sales_cannot_open_integrity_panel(make_user):
    with pytest.raises(AccessDeniedError):
        integrity_service.run_integrity_checks(make_user(Role.SALES))
