import pytest
from streamlit.testing.v1 import AppTest

from domain.access import Role, User
from ui.session import USER_KEY

PAGES = [
    ("products", "render_products_page", "Produtos", "Novo produto"),
    ("green_coffees", "render_green_coffees_page", "Cafés verdes", "Novo café verde"),
    ("farms", "render_farms_page", "Fazendas", "Nova fazenda"),
    ("packaging", "render_packaging_page", "Embalagens", "Nova embalagem"),
    ("customers", "render_customers_page", "Clientes", "Novo cliente"),
    ("suppliers", "render_suppliers_page", "Fornecedores", "Novo fornecedor"),
    ("finance_setup", "render_finance_setup_page", "Categorias e contas", "Nova categoria"),
]


def run_page(module: str, function: str, user: User) -> AppTest:
    app = AppTest.from_string(f"from ui.pages.{module} import {function}\n{function}()")
    app.session_state[USER_KEY] = user
    return app.run(timeout=30)


def button_labels(app: AppTest) -> list[str]:
    return [button.label for button in app.button]


@pytest.mark.parametrize(("module", "function", "title", "new_label"), PAGES)
def test_manager_sees_page_with_create_action(make_user, module, function, title, new_label):
    app = run_page(module, function, make_user(Role.MANAGER))
    assert not app.exception
    assert app.title[0].value == title
    assert new_label in button_labels(app)


@pytest.mark.parametrize(("module", "function", "title", "new_label"), PAGES)
def test_viewer_sees_page_without_create_action(make_user, module, function, title, new_label):
    app = run_page(module, function, make_user(Role.VIEWER))
    assert not app.exception
    assert new_label not in button_labels(app)
