import pytest

from domain.access import Role
from services import purchases as purchases_service
from tests.integration.demo_catalog import build_demo_catalog
from tests.integration.test_master_data_pages import button_labels, run_page

PAGES = [
    ("purchases", "render_purchases_page", "Compras"),
    ("stock", "render_stock_page", "Posição de estoque"),
    ("stock_ledger", "render_stock_ledger_page", "Extrato de estoque"),
    ("finance_entries", "render_finance_entries_page", "Contas a pagar e a receber"),
    ("integrity", "render_integrity_page", "Painel de integridade"),
]


@pytest.mark.parametrize(("module", "function", "title"), PAGES)
def test_manager_opens_operation_pages(make_user, module, function, title):
    manager = make_user(Role.MANAGER)
    catalog = build_demo_catalog(manager)
    purchases_service.create_purchase(manager, catalog.coffee_purchase())
    app = run_page(module, function, manager)
    assert not app.exception
    assert app.title[0].value == title


def test_viewer_sees_purchases_without_new_order(make_user):
    app = run_page("purchases", "render_purchases_page", make_user(Role.VIEWER))
    assert not app.exception
    assert "Nova compra" not in button_labels(app)


def test_production_creates_orders(make_user):
    app = run_page("purchases", "render_purchases_page", make_user(Role.PRODUCTION))
    assert "Nova compra" in button_labels(app)


def test_integrity_panel_reports_all_checks_ok(make_user):
    app = run_page("integrity", "render_integrity_page", make_user(Role.FINANCE))
    assert app.metric[0].value == "3 de 3"
