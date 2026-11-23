from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from core.clock import today
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.brazil import PersonType
from domain.dates import add_months
from domain.finance import (
    EntryDisplayStatus,
    EntryType,
    Granularity,
    ManualEntryInput,
    SettlementInput,
    SettlementMethod,
)
from domain.inventory import AdjustmentReason, StockItemKind, StockItemRef
from domain.partners import CustomerInput, Segment
from domain.sales import Channel, DeliveryType, PaymentMethod, SaleInput, SaleItemInput, ShipmentInput
from services import dashboard as dashboard_service
from services import finance as finance_service
from services import integrity as integrity_service
from services import inventory as inventory_service
from services import partners as partners_service
from services import sales as sales_service
from services import settings as settings_service
from services.finance import CashFlowRequest, EntryFilters
from services.inventory import AdjustmentInput
from tests.integration.demo_catalog import build_stocked_catalog


@pytest.fixture
def manager(make_user):
    return make_user(Role.MANAGER)


@pytest.fixture
def catalog(manager):
    return build_stocked_catalog(manager)


def entries(actor, statuses=tuple(EntryDisplayStatus)) -> list[dict]:
    filters = EntryFilters(today() - timedelta(days=400), today() + timedelta(days=400), None, statuses)
    return finance_service.list_entries(actor, filters)


def entry_id(actor, description_part: str) -> int:
    return next(row["id"] for row in entries(actor) if description_part in row["description"])


def category_id(actor, name: str) -> int:
    return next(row["id"] for row in finance_service.get_entry_form_options(actor).categories if row["name"] == name)


def bank_id(actor) -> int:
    return next(row["id"] for row in finance_service.list_account_balances(actor) if row["kind"] == "BANK")


def run_demo_steps_6_to_9(manager, catalog) -> str:
    ana = partners_service.create_customer(
        manager, CustomerInput("Ana Souza", PersonType.INDIVIDUAL, Segment.CONSUMER, address="Rua das Flores, 10")
    )
    online = sales_service.create_sale(
        manager,
        SaleInput(ana, Channel.ONLINE, DeliveryType.SHIPPING, PaymentMethod.CREDIT_CARD,
                  (SaleItemInput(catalog.product_id, 2),), freight_amount=Decimal("18"),
                  delivery_address="Rua das Flores, 10"),
        confirm=True,
    )  # fmt: skip
    sales_service.ship_sale(manager, online.sale_id, ShipmentInput("BR123456789", Decimal("22")))
    sales_service.deliver_sale(manager, online.sale_id)
    walk_in = next(row["id"] for row in sales_service.get_customer_options(manager) if row["is_system"])
    sales_service.create_sale(
        manager,
        SaleInput(
            walk_in, Channel.LOCAL, DeliveryType.PICKUP, PaymentMethod.PIX, (SaleItemInput(catalog.product_id, 1),)
        ),
        confirm=True,
        deliver_now=True,
    )
    return online.number


def test_demo_steps_10_to_13_expense_settlement_cash_flow_reconciliation(manager, catalog):
    online_number = run_demo_steps_6_to_9(manager, catalog)
    finance_service.create_manual_entry(
        manager,
        ManualEntryInput(category_id(manager, "Gás do torrador"), "Gás do torrador – novembro", Decimal("180"),
                         today() + timedelta(days=10)),
    )  # fmt: skip
    to_settle = (
        entry_id(manager, f"Venda {online_number}"),
        entry_id(manager, "Taxa do cartão"),
        entry_id(manager, "parcela 1/2"),
    )
    assert (
        finance_service.settle_entries(manager, SettlementInput(to_settle, bank_id(manager), SettlementMethod.TRANSFER))
        == 3
    )

    report = finance_service.get_cash_flow(
        manager, CashFlowRequest(today(), today(), (bank_id(manager),), Granularity.DAY)
    )
    assert (report.inflow, report.outflow, report.closing_balance - report.opening_balance) == (
        Decimal("177.70"),
        Decimal("904.47"),
        Decimal("-726.77"),
    )
    [ninety_days] = [bucket for bucket in report.forecast if bucket.horizon_days == 90]
    assert ninety_days.outflow == Decimal("1477.00")

    settled = [row["id"] for row in finance_service.list_reconciliation(manager, bank_id(manager), today(), today())]
    assert len(settled) == 4
    finance_service.set_reconciled(manager, settled, True)
    [bank] = [row for row in finance_service.list_account_balances(manager) if row["kind"] == "BANK"]
    assert bank["reconciled_balance"] == bank["system_balance"] == Decimal("-726.77")
    assert bank["unreconciled_count"] == 0

    inventory_service.adjust_inventory(
        manager,
        AdjustmentInput(StockItemRef(StockItemKind.PRODUCT, catalog.product_id), AdjustmentReason.TASTING,
                        "Degustação na loja", lost_quantity=Decimal("1")),
    )  # fmt: skip
    [month] = finance_service.get_income_statement(manager, today(), today())
    assert (month.net_revenue, month.freight_revenue, month.cost_of_goods) == (
        Decimal("159.70"),
        Decimal("18.00"),
        Decimal("60.02"),
    )
    assert (month.selling_costs, month.stock_adjustments, month.operating_expenses) == (
        Decimal("29.67"),
        Decimal("-20.01"),
        Decimal("180.00"),
    )
    assert month.result == Decimal("-112.00")
    assert month.gross_margin_pct == Decimal("62.4")
    assert all(check.passed for check in integrity_service.run_integrity_checks(manager))


def test_reconciled_entry_cannot_have_settlement_reversed(make_user, manager, catalog):
    entry = entry_id(manager, "parcela 1/2")
    finance_service.settle_entries(manager, SettlementInput((entry,), bank_id(manager), SettlementMethod.PIX))
    finance_service.set_reconciled(manager, [entry], True)
    with pytest.raises(BusinessRuleError, match="conciliado"):
        finance_service.reverse_settlement(manager, entry)
    finance_service.set_reconciled(manager, [entry], False)
    with pytest.raises(AccessDeniedError):
        finance_service.reverse_settlement(make_user(Role.FINANCE), entry)
    finance_service.reverse_settlement(manager, entry)
    assert next(row for row in entries(manager) if row["id"] == entry)["status"] == "PENDING"


def test_settlement_rules(manager, catalog, database_url):
    entry = entry_id(manager, "parcela 1/2")
    with pytest.raises(BusinessRuleError, match="futuro"):
        finance_service.settle_entries(
            manager,
            SettlementInput((entry,), bank_id(manager), SettlementMethod.PIX, today() + timedelta(days=1)),
        )
    with pytest.raises(BusinessRuleError, match="anterior à competência"):
        finance_service.settle_entries(
            manager,
            SettlementInput((entry,), bank_id(manager), SettlementMethod.PIX, today() - timedelta(days=1)),
        )
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE financial_accounts SET is_active = FALSE WHERE kind = 'BANK'")
    with pytest.raises(BusinessRuleError, match="inativa"):
        finance_service.settle_entries(manager, SettlementInput((entry,), bank_id(manager), SettlementMethod.PIX))


def test_batch_settlement_is_all_or_nothing(manager, catalog):
    first, second = [row["id"] for row in entries(manager) if row["description"].startswith("Compra C-")][:2]
    finance_service.settle_entries(manager, SettlementInput((first,), bank_id(manager), SettlementMethod.PIX))
    with pytest.raises(BusinessRuleError, match="pendentes"):
        finance_service.settle_entries(
            manager, SettlementInput((second, first), bank_id(manager), SettlementMethod.PIX)
        )
    assert next(row for row in entries(manager) if row["id"] == second)["status"] == "PENDING"


def test_manual_entries_with_recurrence_and_cancellation(make_user, manager, catalog):
    finance_user = make_user(Role.FINANCE)
    rent = category_id(finance_user, "Aluguel")
    due = today() + timedelta(days=5)
    ids = finance_service.create_manual_entry(
        finance_user, ManualEntryInput(rent, "Aluguel da loja", Decimal("1200"), due, repeat_months=3)
    )
    rows = [row for row in entries(finance_user) if row["id"] in ids]
    assert [(row["description"], row["due_date"]) for row in rows] == [
        (f"Aluguel da loja ({index}/3)", add_months(due, index - 1)) for index in (1, 2, 3)
    ]
    finance_service.cancel_manual_entry(finance_user, ids[2], "Contrato encerrado")
    with pytest.raises(BusinessRuleError, match="cancelados pelo documento"):
        finance_service.cancel_manual_entry(finance_user, entry_id(manager, "parcela 1/2"), "Teste")
    with pytest.raises(AccessDeniedError):
        finance_service.create_manual_entry(make_user(Role.SALES), ManualEntryInput(rent, "Aluguel", Decimal("1"), due))


def test_manual_entry_refuses_stock_categories(manager, catalog, database_url):
    with psycopg.connect(database_url) as connection:
        inventory_category = connection.execute(
            "SELECT id FROM financial_categories WHERE name = 'Compra de café verde'"
        ).fetchone()[0]
    with pytest.raises(BusinessRuleError, match="despesa operacional ou de outras receitas"):
        finance_service.create_manual_entry(
            manager, ManualEntryInput(inventory_category, "Café", Decimal("10"), today())
        )


def test_home_summary_shows_overdue_and_due_soon(manager, catalog, database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE financial_entries SET due_date = %s WHERE description LIKE 'Compra C-%%parcela 1/2'",
            (today() - timedelta(days=3),),
        )
    summary = dashboard_service.get_home_summary(manager)
    assert (summary.payables.overdue_count, summary.payables.overdue_amount) == (1, Decimal("900.00"))
    assert summary.sales["month_count"] == 0


def test_admin_updates_settings_with_audit(make_user, catalog):
    admin = make_user(Role.ADMIN)
    assert settings_service.update_settings(admin, {"max_discount_pct": "12,5", "quote_validity_days": "7"}) == [
        "max_discount_pct"
    ]
    [history] = settings_service.list_settings_history(admin)
    assert (history["old_data"]["value"], history["new_data"]["value"]) == ("10", "12.5")
    assert settings_service.update_settings(admin, {"default_shipping_box_id": str(catalog.box_id)})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_discount_pct": "150"}, "deve ficar entre"),
        ({"quote_validity_days": "2.5"}, "inteiro"),
        ({"credit_card_fee_pct": "abc"}, "número"),
        ({"weight_loss_warn_min_pct": "30"}, "alerta"),
        ({"operation_start_date": "2026-13-01"}, "data válida"),
    ],
)
def test_invalid_settings_are_refused(make_user, changes, message):
    with pytest.raises(BusinessRuleError, match=message):
        settings_service.update_settings(make_user(Role.ADMIN), changes)


def test_shipping_box_setting_must_be_a_box_and_admin_only(make_user, manager, catalog):
    admin = make_user(Role.ADMIN)
    with pytest.raises(BusinessRuleError, match="caixa de envio"):
        settings_service.update_settings(admin, {"default_shipping_box_id": str(catalog.bag_id)})
    with pytest.raises(AccessDeniedError):
        settings_service.update_settings(manager, {"max_discount_pct": "5"})


def test_receivable_type_is_kept_for_other_revenue(manager, catalog):
    [entry_id_] = finance_service.create_manual_entry(
        manager, ManualEntryInput(category_id(manager, "Outras receitas"), "Curso de barista", Decimal("300"), today())
    )
    row = next(row for row in entries(manager) if row["id"] == entry_id_)
    assert row["entry_type"] == EntryType.RECEIVABLE
