"""Rehearsal of the VA1 demo script (spec section 12): the 14 steps in order, on one database, with expected values."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from core.clock import today
from core.errors import BusinessRuleError
from domain.access import Permission, Role, has_permission
from domain.brazil import PersonType
from domain.catalog import PackagingItemInput, PackagingKind, RoastProfile
from domain.finance import EntryDisplayStatus, Granularity, ManualEntryInput, SettlementInput, SettlementMethod
from domain.inventory import AdjustmentReason, StockItemKind, StockItemRef
from domain.partners import CustomerInput, Segment
from domain.production import PackingInput, RoastBatchStatus, RoastInput
from domain.purchasing import PurchaseStatus
from domain.sales import Channel, DeliveryType, PaymentMethod, SaleInput, SaleItemInput, ShipmentInput
from services import catalog as catalog_service
from services import finance as finance_service
from services import integrity as integrity_service
from services import inventory as inventory_service
from services import partners as partners_service
from services import production as production_service
from services import purchases as purchases_service
from services import sales as sales_service
from services.finance import CashFlowRequest, EntryFilters
from services.inventory import AdjustmentInput
from services.production import PeriodFilters
from services.purchases import PurchaseFilters
from tests.integration.demo_catalog import build_demo_catalog, demo_product


def stock(actor, kind: StockItemKind, item_id: int):
    return inventory_service.get_stock_balance(actor, StockItemRef(kind, item_id))


def entry_id(actor, description_part: str) -> int:
    filters = EntryFilters(today() - timedelta(days=5), today() + timedelta(days=90), None, tuple(EntryDisplayStatus))
    rows = finance_service.list_entries(actor, filters)
    return next(row["id"] for row in rows if description_part in row["description"])


def test_demo_script_runs_end_to_end(make_user):
    manager, viewer = make_user(Role.MANAGER), make_user(Role.VIEWER)

    # 1. Manager sees write actions; the visitor does not.
    assert has_permission(manager, Permission.MANAGE_SALES)
    assert not has_permission(viewer, Permission.MANAGE_SALES)

    # 2. Master data, with the 500 g bag refused for a 250 g product (RN-10).
    catalog = build_demo_catalog(manager)
    bag_500 = catalog_service.create_packaging_item(manager, PackagingItemInput("Pacote 500 g", PackagingKind.BAG, 500))
    with pytest.raises(BusinessRuleError, match="não serve para 250 g"):
        catalog_service.create_product(manager, demo_product(catalog.coffee_id, bag_500, catalog.label_id))
    ana = partners_service.create_customer(
        manager, CustomerInput("Ana Souza", PersonType.INDIVIDUAL, Segment.CONSUMER, address="Rua das Flores, 10")
    )

    # 3. Purchases received: stock, average costs and three payables.
    for data in (catalog.coffee_purchase(), catalog.packaging_purchase()):
        purchases_service.create_purchase(manager, data)
    for purchase in purchases_service.list_purchases(
        manager, PurchaseFilters(today(), today(), None, (PurchaseStatus.PENDING,))
    ):
        purchases_service.receive_purchase(manager, purchase["id"])
    coffee = stock(manager, StockItemKind.GREEN_COFFEE, catalog.coffee_id)
    assert (coffee.stock, coffee.unit_cost) == (Decimal("30.000"), Decimal("60.0000"))

    # 4. Roasting, with the capacity and weight-loss blocks.
    for green, roasted, message in (("18", "15", "capacidade"), ("10", "6", "40,00%")):
        with pytest.raises(BusinessRuleError, match=message):
            production_service.roast(
                manager, RoastInput(catalog.coffee_id, RoastProfile.MEDIUM, Decimal(green), Decimal(roasted))
            )
    roast = production_service.roast(
        manager, RoastInput(catalog.coffee_id, RoastProfile.MEDIUM, Decimal("10"), Decimal("8.4"))
    )
    assert (roast.weight_loss_pct, roast.cost_per_kg) == (Decimal("16.00"), Decimal("71.4286"))
    assert stock(manager, StockItemKind.GREEN_COFFEE, catalog.coffee_id).stock == Decimal("20.000")

    # 5. Packing 20 bags.
    [batch] = production_service.list_roast_batches(manager, PeriodFilters(today(), today()), (RoastBatchStatus.OPEN,))
    packing = production_service.pack(manager, PackingInput(catalog.product_id, batch["id"], 20))
    assert packing.unit_cost == Decimal("20.0071")
    assert stock(manager, StockItemKind.ROAST_BATCH, batch["id"]).stock == Decimal("3.400")
    assert stock(manager, StockItemKind.PACKAGING_ITEM, catalog.bag_id).stock == Decimal("80")

    # 6. Online quote, then confirmation.
    online = SaleInput(ana, Channel.ONLINE, DeliveryType.SHIPPING, PaymentMethod.CREDIT_CARD,
                       (SaleItemInput(catalog.product_id, 2),), freight_amount=Decimal("18"),
                       delivery_address="Rua das Flores, 10")  # fmt: skip
    quote = sales_service.create_sale(manager, online)
    assert stock(manager, StockItemKind.PRODUCT, catalog.product_id).stock == Decimal("20")
    confirmed = sales_service.confirm_sale(manager, quote.sale_id)
    assert [entry.amount for entry in confirmed.effects.entries] == [Decimal("127.80"), Decimal("4.47")]
    assert (confirmed.products_cost, confirmed.margin_pct) == (Decimal("40.01"), Decimal("63.6"))
    assert stock(manager, StockItemKind.PACKAGING_ITEM, catalog.box_id).stock == Decimal("49")

    # 7. Shipping and delivery.
    freight = sales_service.ship_sale(manager, quote.sale_id, ShipmentInput("BR123456789", Decimal("22")))
    assert [entry.amount for entry in freight.entries] == [Decimal("22")]
    sales_service.deliver_sale(manager, quote.sale_id)
    events = sales_service.get_sale_detail(manager, quote.sale_id).events
    assert [event["to_status"] for event in events] == ["QUOTE", "CONFIRMED", "SHIPPED", "DELIVERED"]

    # 8. Counter sale paid by PIX, already settled and without boxes.
    walk_in = next(row["id"] for row in sales_service.get_customer_options(manager) if row["is_system"])
    counter = SaleInput(walk_in, Channel.LOCAL, DeliveryType.PICKUP, PaymentMethod.PIX,
                        (SaleItemInput(catalog.product_id, 1),))  # fmt: skip
    pix = sales_service.create_sale(manager, counter, confirm=True, deliver_now=True)
    assert [entry.action for entry in pix.effects.entries] == ["settled"]
    assert stock(manager, StockItemKind.PRODUCT, catalog.product_id).stock == Decimal("17")
    assert stock(manager, StockItemKind.PACKAGING_ITEM, catalog.box_id).stock == Decimal("49")

    # 9. Selling 30 bags is refused and the stock stays the same.
    too_many = replace(counter, items=(SaleItemInput(catalog.product_id, 30),))
    with pytest.raises(BusinessRuleError, match="Estoque insuficiente: CC-BVCAT-MED-GR-250 .* tem 17 un"):
        sales_service.create_sale(manager, too_many, confirm=True)
    assert stock(manager, StockItemKind.PRODUCT, catalog.product_id).stock == Decimal("17")

    # 10. Expense and settlements: realised cash flow of the day.
    gas = next(row["id"] for row in finance_service.get_entry_form_options(manager).categories
               if row["name"] == "Gás do torrador")  # fmt: skip
    finance_service.create_manual_entry(
        manager, ManualEntryInput(gas, "Gás do torrador – novembro", Decimal("180"), today() + timedelta(days=10))
    )
    bank = next(row["id"] for row in finance_service.list_account_balances(manager) if row["kind"] == "BANK")
    to_settle = (entry_id(manager, f"Venda {quote.number}"), entry_id(manager, "Taxa do cartão"),
                 entry_id(manager, "parcela 1/2"))  # fmt: skip
    finance_service.settle_entries(manager, SettlementInput(to_settle, bank, SettlementMethod.TRANSFER))
    cash = finance_service.get_cash_flow(manager, CashFlowRequest(today(), today(), (bank,), Granularity.DAY))
    assert (cash.inflow, cash.outflow, cash.closing_balance - cash.opening_balance) == (
        Decimal("177.70"), Decimal("904.47"), Decimal("-726.77"),
    )  # fmt: skip

    # 11. Reconciling the four bank entries.
    settled = [row["id"] for row in finance_service.list_reconciliation(manager, bank, today(), today())]
    finance_service.set_reconciled(manager, settled, True)
    [account] = [row for row in finance_service.list_account_balances(manager) if row["id"] == bank]
    assert len(settled) == 4 and account["reconciled_balance"] == account["system_balance"]

    # 12. One bag used for tasting.
    tasting = inventory_service.adjust_inventory(
        manager,
        AdjustmentInput(StockItemRef(StockItemKind.PRODUCT, catalog.product_id), AdjustmentReason.TASTING,
                        "Degustação na loja", lost_quantity=Decimal("1")),
    )  # fmt: skip
    assert [(change.before, change.after) for change in tasting.stock] == [(Decimal("17"), Decimal("16"))]

    # 13. Integrity panel.
    assert all(check.passed for check in integrity_service.run_integrity_checks(manager))

    # 14. A confirmed card sale cancelled by the manager.
    card = sales_service.create_sale(manager, replace(counter, payment_method=PaymentMethod.CREDIT_CARD), confirm=True)
    effects = sales_service.cancel_sale(manager, card.sale_id, "Cliente desistiu")
    assert [entry.action for entry in effects.entries] == ["cancelled", "cancelled"]
    assert stock(manager, StockItemKind.PRODUCT, catalog.product_id).stock == Decimal("16")
    assert all(check.passed for check in integrity_service.run_integrity_checks(manager))
