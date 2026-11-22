import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.catalog import BAG_CAPACITIES_G, Grind, PackagingKind, ProductInput, RoastProfile, build_sku
from services import catalog as catalog_service
from ui.feedback import show_flash
from ui.formatting import to_float
from ui.forms import enum_selectbox, form_key, index_of, record_selectbox, to_decimal
from ui.labels import ACTIVE_LABELS, GRIND_LABELS, ROAST_PROFILE_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

PAGE_KEY = "products"

DECIMAL_PLACES = {"Loja (R$)": 2, "Online (R$)": 2, "Atacado (R$)": 2, "Estoque (un.)": 0, "Custo médio (R$)": 2}


def _products_table(products: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "SKU": [row["sku"] for row in products],
            "Nome": [row["name"] for row in products],
            "Torra": [ROAST_PROFILE_LABELS[RoastProfile(row["roast_profile"])] for row in products],
            "Moagem": [GRIND_LABELS[Grind(row["grind"])] for row in products],
            "Peso (g)": [row["weight_g"] for row in products],
            "Loja (R$)": [to_float(row["price_local"]) for row in products],
            "Online (R$)": [to_float(row["price_online"]) for row in products],
            "Atacado (R$)": [to_float(row["price_wholesale"]) for row in products],
            "Estoque (un.)": [row["stock"] for row in products],
            "Custo médio (R$)": [to_float(row["avg_unit_cost"]) for row in products],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in products],
        }
    )


def _render_price_inputs(record: Record, key: str, disabled: bool) -> tuple[float, float, float | None]:
    local_column, online_column, wholesale_column = st.columns(3)
    price_inputs = {"min_value": 0.0, "step": 1.0, "format": "%.2f", "disabled": disabled}
    price_local = local_column.number_input(
        "Preço na loja (R$)", value=to_float(record.get("price_local")), key=f"{key}_price_local", **price_inputs
    )
    price_online = online_column.number_input(
        "Preço online (R$)", value=to_float(record.get("price_online")), key=f"{key}_price_online", **price_inputs
    )
    price_wholesale = wholesale_column.number_input(
        "Preço de atacado (R$)",
        value=to_float(record.get("price_wholesale")),
        key=f"{key}_price_wholesale",
        help="Deixe em branco se o produto não é vendido no atacado.",
        **price_inputs,
    )
    if disabled:
        st.caption("Somente gerente ou administrador altera preços.")
    return price_local, price_online, price_wholesale


def _render_product_form(actor: User, record: Record | None) -> None:
    key = form_key(PAGE_KEY, record)
    record = record or {}
    is_editing = bool(record)
    coffees = catalog_service.list_green_coffee_options(actor, record.get("green_coffee_id"))
    coffees_by_id = {coffee["id"]: coffee for coffee in coffees}
    left, right = st.columns(2)
    green_coffee_id = record_selectbox(
        left,
        "Café verde de origem",
        coffees,
        record.get("green_coffee_id"),
        f"{key}_coffee",
        lambda coffee: f"{coffee['code']} · {coffee['name']} ({coffee['harvest_year']})",
        disabled=is_editing,
    )
    name = right.text_input("Nome do produto", value=record.get("name", ""), key=f"{key}_name")
    roast_profile = enum_selectbox(
        left, "Perfil de torra", ROAST_PROFILE_LABELS, record.get("roast_profile"), f"{key}_roast", is_editing
    )
    grind = enum_selectbox(right, "Moagem", GRIND_LABELS, record.get("grind"), f"{key}_grind", is_editing)
    weight_g = left.selectbox(
        "Peso líquido",
        BAG_CAPACITIES_G,
        index=index_of(BAG_CAPACITIES_G, record.get("weight_g")) or 0,
        format_func=lambda grams: f"{grams} g",
        key=f"{key}_weight",
        disabled=is_editing,
    )
    bags = [
        bag
        for bag in catalog_service.list_packaging_options(actor, PackagingKind.BAG, record.get("bag_id"))
        if bag["capacity_g"] == weight_g
    ]
    bag_id = record_selectbox(
        right, f"Pacote de {weight_g} g", bags, record.get("bag_id"), f"{key}_bag", lambda bag: bag["name"]
    )
    label_id = record_selectbox(
        left,
        "Etiqueta",
        catalog_service.list_packaging_options(actor, PackagingKind.LABEL, record.get("label_id")),
        record.get("label_id"),
        f"{key}_label",
        lambda label: label["name"],
    )
    min_stock = right.number_input(
        "Estoque mínimo (un.)", min_value=0, step=5, value=record.get("min_stock", 0), key=f"{key}_min_stock"
    )
    location = st.text_input("Localização na prateleira", value=record.get("location") or "", key=f"{key}_location")
    can_price = has_permission(actor, Permission.MANAGE_PRICES)
    price_local, price_online, price_wholesale = _render_price_inputs(record, key, disabled=not can_price)
    if green_coffee_id is not None:
        sku = record.get("sku") or build_sku(coffees_by_id[green_coffee_id]["code"], roast_profile, grind, weight_g)
        st.caption(f"SKU: **{sku}**")
    data = ProductInput(
        name,
        green_coffee_id,
        roast_profile,
        grind,
        weight_g,
        bag_id,
        label_id,
        to_decimal(price_local),
        to_decimal(price_online),
        to_decimal(price_wholesale),
        int(min_stock),
        location,
    )
    render_save_button(
        PAGE_KEY,
        record or None,
        "Cadastrar produto",
        lambda: catalog_service.create_product(actor, data),
        lambda product_id: catalog_service.update_product(actor, product_id, data),
        f"Produto cadastrado: {data.name}.",
        f"Produto atualizado: {data.name}.",
    )


def render_products_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Produtos")
    st.caption("Os SKUs vendidos: café, torra, moagem e peso, com pacote, etiqueta e preço por canal.")
    render_record_list(
        RecordList(
            key=PAGE_KEY,
            noun="produto",
            new_label="Novo produto",
            search_placeholder="Buscar por SKU, nome ou café",
            empty_message="Nenhum produto cadastrado. Cadastre o café verde, o pacote e a etiqueta antes.",
            can_write=has_permission(actor, Permission.MANAGE_PRODUCTS),
            can_create=has_permission(actor, Permission.MANAGE_PRICES),
            load=lambda filters: catalog_service.list_products(actor, filters.search, filters.include_inactive),
            to_table=_products_table,
            decimal_places=DECIMAL_PLACES,
            describe=lambda record: f"{record['sku']} · {record['name']}",
            open_form=lambda record: open_record_form(
                "Editar produto" if record else "Novo produto",
                lambda: _render_product_form(actor, record),
            ),
            delete=lambda record_id: catalog_service.delete_product(actor, record_id),
            set_active=lambda record_id, is_active: catalog_service.set_product_active(actor, record_id, is_active),
        )
    )
