import streamlit as st
from streamlit.navigation.page import StreamlitPage

from domain.access import Permission, User, has_permission
from ui.pages.customers import render_customers_page
from ui.pages.farms import render_farms_page
from ui.pages.finance_entries import render_finance_entries_page
from ui.pages.finance_setup import render_finance_setup_page
from ui.pages.green_coffees import render_green_coffees_page
from ui.pages.harvests import render_harvests_page
from ui.pages.home import render_home_page
from ui.pages.integrity import render_integrity_page
from ui.pages.packaging import render_packaging_page
from ui.pages.packing import render_packing_page
from ui.pages.products import render_products_page
from ui.pages.purchases import render_purchases_page
from ui.pages.roasting import render_roasting_page
from ui.pages.sales import render_sales_page
from ui.pages.stock import render_stock_page
from ui.pages.stock_ledger import render_stock_ledger_page
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
    if has_permission(user, Permission.VIEW_FINANCE):
        pages.append(
            st.Page(
                render_finance_setup_page,
                title="Categorias e contas",
                icon=":material/account_balance:",
                url_path="categorias-e-contas",
            )
        )
    return pages


def _operation_sections(user: User) -> dict[str, list[StreamlitPage]]:
    sections: dict[str, list[StreamlitPage]] = {}
    if has_permission(user, Permission.VIEW_SALES):
        sections["Vendas"] = [
            st.Page(render_sales_page, title="Vendas", icon=":material/point_of_sale:", url_path="vendas"),
        ]
    if has_permission(user, Permission.VIEW_PURCHASES):
        sections["Compras"] = [
            st.Page(render_purchases_page, title="Compras", icon=":material/shopping_cart:", url_path="compras"),
        ]
    if has_permission(user, Permission.VIEW_PRODUCTION):
        sections["Produção"] = [
            st.Page(render_harvests_page, title="Colheitas", icon=":material/grass:", url_path="colheitas"),
            st.Page(render_roasting_page, title="Torras", icon=":material/local_fire_department:", url_path="torras"),
            st.Page(render_packing_page, title="Envases", icon=":material/shopping_bag:", url_path="envases"),
        ]
    sections["Estoque"] = [
        st.Page(render_stock_page, title="Posição de estoque", icon=":material/inventory_2:", url_path="estoque"),
        st.Page(render_stock_ledger_page, title="Extrato", icon=":material/receipt_long:", url_path="extrato"),
    ]
    if has_permission(user, Permission.VIEW_FINANCE):
        sections["Financeiro"] = [
            st.Page(
                render_finance_entries_page,
                title="Contas a pagar e a receber",
                icon=":material/payments:",
                url_path="contas",
            ),
        ]
    return sections


def _administration_pages(user: User) -> list[StreamlitPage]:
    pages = []
    if has_permission(user, Permission.MANAGE_USERS):
        pages.append(st.Page(render_users_page, title="Usuários", icon=":material/group:", url_path="usuarios"))
    if has_permission(user, Permission.VIEW_INTEGRITY):
        pages.append(
            st.Page(
                render_integrity_page, title="Painel de integridade", icon=":material/verified:", url_path="integridade"
            )
        )
    return pages


def build_navigation(user: User) -> StreamlitPage:
    sections: dict[str, list[StreamlitPage]] = {
        "Geral": [
            st.Page(render_home_page, title="Início", icon=":material/home:", url_path="inicio", default=True),
        ],
        **_operation_sections(user),
        "Cadastros": _master_data_pages(user),
    }
    if administration := _administration_pages(user):
        sections["Administração"] = administration
    return st.navigation(sections, expanded=True)
