from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from core.clock import today
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.finance import EntryDisplayStatus
from domain.inventory import AdjustmentReason, StockItemKind, StockItemRef
from domain.purchasing import PurchaseItemInput, PurchaseStatus
from repositories import finance as finance_repository
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


def find_purchase_id(manager, number: str) -> int:
    filters = PurchaseFilters(today() - timedelta(days=1), today(), None, tuple(PurchaseStatus))
    return next(row["id"] for row in purchases_service.list_purchases(manager, filters) if row["number"] == number)


def create_and_receive(manager, data):
    purchase_id = find_purchase_id(manager, purchases_service.create_purchase(manager, data))
    return purchase_id, purchases_service.receive_purchase(manager, purchase_id)


def positions(manager, kind: StockItemKind) -> dict[str, tuple[Decimal, Decimal]]:
    return {
        row["label"]: (row["stock"], row["unit_cost"]) for row in inventory_service.list_stock_positions(manager, kind)
    }


def test_demo_step_3_receives_coffee_and_packaging(manager, catalog):
    coffee_purchase_id, coffee_effects = create_and_receive(manager, catalog.coffee_purchase())
    _, packaging_effects = create_and_receive(manager, catalog.packaging_purchase())

    coffee = positions(manager, StockItemKind.GREEN_COFFEE)["BVCAT · Boa Vista Catuaí Amarelo"]
    assert coffee == (Decimal("30.000"), Decimal("60.0000"))
    packaging = positions(manager, StockItemKind.PACKAGING_ITEM)
    assert packaging["Pacote valvulado 250 g"] == (Decimal("100"), Decimal("1.8000"))
    assert packaging["Etiqueta padrão"] == (Decimal("100"), Decimal("0.3500"))
    assert packaging["Caixa de envio P"] == (Decimal("50"), Decimal("3.2000"))

    amounts = [entry.amount for entry in coffee_effects.entries + packaging_effects.entries]
    assert amounts == [Decimal("900.00"), Decimal("900.00"), Decimal("375.00")]
    due_dates = [entry.due_date for entry in coffee_effects.entries]
    assert due_dates == [today() + timedelta(days=30), today() + timedelta(days=60)]
    assert packaging_effects.entries[0].due_date == today() + timedelta(days=28)
    assert [change.after for change in coffee_effects.stock] == [Decimal("30.000")]

    detail = purchases_service.get_purchase_detail(manager, coffee_purchase_id)
    assert detail.purchase["status"] == "RECEIVED"
    assert [row["display_status"] for row in detail.entries] == [EntryDisplayStatus.PENDING] * 2
    assert len(detail.movements) == 1


def test_freight_is_absorbed_into_average_cost(manager, catalog):
    create_and_receive(manager, catalog.coffee_purchase(freight_amount=Decimal("90")))
    coffee = positions(manager, StockItemKind.GREEN_COFFEE)["BVCAT · Boa Vista Catuaí Amarelo"]
    assert coffee == (Decimal("30.000"), Decimal("63.0000"))


def test_second_purchase_updates_weighted_average_cost(manager, catalog):
    create_and_receive(manager, catalog.coffee_purchase(installments=1))
    items = (PurchaseItemInput(StockItemKind.GREEN_COFFEE, catalog.coffee_id, Decimal("30"), Decimal("66")),)
    create_and_receive(manager, catalog.coffee_purchase(items=items, installments=1))
    coffee = positions(manager, StockItemKind.GREEN_COFFEE)["BVCAT · Boa Vista Catuaí Amarelo"]
    assert coffee == (Decimal("60.000"), Decimal("63.0000"))


def test_receiving_twice_is_rejected(manager, catalog):
    purchase_id, _ = create_and_receive(manager, catalog.coffee_purchase())
    with pytest.raises(BusinessRuleError, match="não está pendente"):
        purchases_service.receive_purchase(manager, purchase_id)


def test_failed_receipt_rolls_back_everything(manager, catalog, monkeypatch):
    purchase_id = find_purchase_id(manager, purchases_service.create_purchase(manager, catalog.coffee_purchase()))

    def fail(*args, **kwargs):
        raise RuntimeError("falha simulada no financeiro")

    monkeypatch.setattr(finance_repository, "insert_entry", fail)
    with pytest.raises(RuntimeError):
        purchases_service.receive_purchase(manager, purchase_id)
    monkeypatch.undo()

    detail = purchases_service.get_purchase_detail(manager, purchase_id)
    assert detail.purchase["status"] == "PENDING"
    assert detail.movements == [] and detail.entries == []
    assert detail.items[0]["effective_unit_cost"] is None
    assert positions(manager, StockItemKind.GREEN_COFFEE)["BVCAT · Boa Vista Catuaí Amarelo"][0] == 0


def test_coffee_must_come_from_supplier_farm(manager, catalog):
    other = catalog.packaging_purchase()
    with pytest.raises(BusinessRuleError):
        purchases_service.create_purchase(manager, replace(other, supplier_id=catalog.coffee_supplier_id))


def test_pending_purchase_can_be_edited_and_cancelled(manager, catalog):
    purchase_id = find_purchase_id(manager, purchases_service.create_purchase(manager, catalog.coffee_purchase()))
    purchases_service.update_purchase(manager, purchase_id, catalog.coffee_purchase(freight_amount=Decimal("45")))
    assert purchases_service.get_purchase_detail(manager, purchase_id).purchase["total_amount"] == Decimal("1845.00")
    with pytest.raises(BusinessRuleError, match="motivo"):
        purchases_service.cancel_purchase(manager, purchase_id, " ")
    purchases_service.cancel_purchase(manager, purchase_id, "Fornecedor sem safra")
    with pytest.raises(BusinessRuleError):
        purchases_service.receive_purchase(manager, purchase_id)


def test_reversal_returns_stock_cost_and_cancels_payables(manager, catalog):
    create_and_receive(manager, catalog.coffee_purchase(installments=1))
    items = (PurchaseItemInput(StockItemKind.GREEN_COFFEE, catalog.coffee_id, Decimal("30"), Decimal("66")),)
    purchase_id, _ = create_and_receive(manager, catalog.coffee_purchase(items=items))
    effects = purchases_service.reverse_purchase(manager, purchase_id, "Lote recusado na prova")
    assert [entry.action for entry in effects.entries] == ["cancelled", "cancelled"]
    coffee = positions(manager, StockItemKind.GREEN_COFFEE)["BVCAT · Boa Vista Catuaí Amarelo"]
    assert coffee == (Decimal("30.000"), Decimal("60.0000"))
    assert purchases_service.get_purchase_detail(manager, purchase_id).purchase["status"] == "REVERSED"


def test_reversal_needs_the_received_stock(manager, catalog):
    purchase_id, _ = create_and_receive(manager, catalog.coffee_purchase())
    item = StockItemRef(StockItemKind.GREEN_COFFEE, catalog.coffee_id)
    inventory_service.adjust_inventory(
        manager, AdjustmentInput(item, AdjustmentReason.LOSS, "Saca molhada", lost_quantity=Decimal("1"))
    )
    with pytest.raises(BusinessRuleError, match="Estoque insuficiente"):
        purchases_service.reverse_purchase(manager, purchase_id, "Devolução")


def test_reversal_is_blocked_after_a_payment(manager, catalog, database_url):
    purchase_id, _ = create_and_receive(manager, catalog.coffee_purchase())
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            UPDATE financial_entries SET status = 'SETTLED', settled_date = current_date, account_id = 1
            WHERE source_module = 'PURCHASES' AND source_id = %s AND installment = 1
            """,
            (purchase_id,),
        )
    with pytest.raises(BusinessRuleError, match="pagas"):
        purchases_service.reverse_purchase(manager, purchase_id, "Devolução")


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(Role.PRODUCTION, True), (Role.FINANCE, True), (Role.SALES, False), (Role.VIEWER, False)],
)
def test_purchase_creation_follows_role_matrix(make_user, catalog, role, allowed):
    user = make_user(role)
    if allowed:
        assert purchases_service.create_purchase(user, catalog.coffee_purchase()).startswith("C-")
    else:
        with pytest.raises(AccessDeniedError):
            purchases_service.create_purchase(user, catalog.coffee_purchase())


def test_finance_cannot_receive_and_production_cannot_cancel(make_user, manager, catalog):
    purchase_id = find_purchase_id(manager, purchases_service.create_purchase(manager, catalog.coffee_purchase()))
    with pytest.raises(AccessDeniedError):
        purchases_service.receive_purchase(make_user(Role.FINANCE), purchase_id)
    with pytest.raises(AccessDeniedError):
        purchases_service.cancel_purchase(make_user(Role.PRODUCTION), purchase_id, "Teste")


def test_only_admin_backdates_receipt(make_user, manager, catalog):
    purchase_id = find_purchase_id(manager, purchases_service.create_purchase(manager, catalog.coffee_purchase()))
    with pytest.raises(AccessDeniedError):
        purchases_service.receive_purchase(manager, purchase_id, today() - timedelta(days=3))
