import streamlit as st
from streamlit.navigation.page import StreamlitPage

from domain.access import Permission, User, has_permission
from ui.pages.customers import render_customers_page
from ui.pages.farms import render_farms_page
from ui.pages.finance_setup import render_finance_setup_page
from ui.pages.green_coffees import render_green_coffees_page
from ui.pages.home import render_home_page
from ui.pages.packaging import render_packaging_page
from ui.pages.products import render_products_page
from ui.pages.suppliers import render_suppliers_page
from ui.pages.users import render_users_page


def _master_data_pages(user: User) -> list[StreamlitPage]:
    pages = [
        st.Page(render_products_page, title="Produtos", icon=":material/sell:", url_path="produtos"),
        st.Page(render_green_coffees_page, title="Cafés verdes", icon=":material/eco:", url_path="cafes-verdes"),
        st.Page(render_farms_page, title="Fazendas", icon=":material/agriculture:", url_path="fazendas"),
        st.Page(render_packaging_page, title="Embalagens", icon=":material/package_2:", url_path="embalagens"),
        st.Page(render_customers_page, title="Clientes", icon=":material/storefront:", url_path="clientes"),
        st.Page(render_suppliers_page, title="Fornecedores", icon=":material/handshake:", url_path="fornecedores"),
    ]
    if has_permission(user, Permission.VIEW_FINANCE_SETUP):
        pages.append(
            st.Page(
                render_finance_setup_page,
                title="Categorias e contas",
                icon=":material/account_balance:",
                url_path="categorias-e-contas",
            )
        )
    return pages


def build_navigation(user: User) -> StreamlitPage:
    sections: dict[str, list[StreamlitPage]] = {
        "Geral": [
            st.Page(render_home_page, title="Início", icon=":material/home:", url_path="inicio", default=True),
        ],
        "Cadastros": _master_data_pages(user),
    }
    if has_permission(user, Permission.MANAGE_USERS):
        sections["Administração"] = [
            st.Page(render_users_page, title="Usuários", icon=":material/group:", url_path="usuarios"),
        ]
    return st.navigation(sections)
