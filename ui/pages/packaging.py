import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.catalog import BAG_CAPACITIES_G, PackagingItemInput, PackagingKind
from services import catalog as catalog_service
from ui.feedback import show_flash
from ui.formatting import to_float
from ui.forms import enum_selectbox, form_key, index_of
from ui.labels import ACTIVE_LABELS, PACKAGING_KIND_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

PAGE_KEY = "packaging"

DECIMAL_PLACES = {"Estoque (un.)": 0, "Mínimo (un.)": 0, "Custo médio (R$)": 2}


def _packaging_table(items: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [row["name"] for row in items],
            "Tipo": [PACKAGING_KIND_LABELS[PackagingKind(row["kind"])] for row in items],
            "Capacidade (g)": [row["capacity_g"] for row in items],
            "Estoque (un.)": [row["stock"] for row in items],
            "Mínimo (un.)": [row["min_stock"] for row in items],
            "Custo médio (R$)": [to_float(row["avg_unit_cost"]) for row in items],
            "Local": [row["location"] for row in items],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in items],
        }
    )


def _render_capacity_input(column, kind: PackagingKind, value: int | None, key: str) -> int | None:
    if kind is PackagingKind.BAG:
        return column.selectbox(
            "Capacidade",
            BAG_CAPACITIES_G,
            index=index_of(BAG_CAPACITIES_G, value) or 0,
            format_func=lambda grams: f"{grams} g",
            key=f"{key}_bag_capacity",
        )
    if kind is PackagingKind.SHIPPING_BOX:
        return column.number_input(
            "Capacidade (g)",
            min_value=1,
            step=250,
            value=value or 2000,
            key=f"{key}_box_capacity",
            help="Peso de café que cabe na caixa. Define quantas caixas um pedido enviado consome.",
        )
    return None


def _render_packaging_form(actor: User, record: Record | None) -> None:
    key = form_key(PAGE_KEY, record)
    record = record or {}
    left, right = st.columns(2)
    name = left.text_input("Nome", value=record.get("name", ""), key=f"{key}_name")
    kind = enum_selectbox(right, "Tipo", PACKAGING_KIND_LABELS, record.get("kind"), f"{key}_kind")
    capacity_g = _render_capacity_input(left, kind, record.get("capacity_g"), key)
    min_stock = right.number_input(
        "Estoque mínimo (un.)", min_value=0, step=10, value=record.get("min_stock", 0), key=f"{key}_min_stock"
    )
    location = left.text_input("Localização no armazém", value=record.get("location") or "", key=f"{key}_location")
    data = PackagingItemInput(name, kind, capacity_g, int(min_stock), location)
    render_save_button(
        PAGE_KEY,
        record or None,
        "Cadastrar embalagem",
        lambda: catalog_service.create_packaging_item(actor, data),
        lambda packaging_item_id: catalog_service.update_packaging_item(actor, packaging_item_id, data),
        f"Embalagem cadastrada: {data.name}.",
        f"Embalagem atualizada: {data.name}.",
    )


def render_packaging_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Embalagens")
    st.caption("Pacotes, etiquetas e caixas de envio. Estoque e custo médio vêm das compras e do consumo no envase.")
    render_record_list(
        RecordList(
            key=PAGE_KEY,
            noun="embalagem",
            new_label="Nova embalagem",
            search_placeholder="Buscar por nome ou localização",
            empty_message="Nenhuma embalagem cadastrada. Use Nova embalagem para cadastrar a primeira.",
            can_write=has_permission(actor, Permission.MANAGE_CATALOG),
            load=lambda filters: catalog_service.list_packaging_items(actor, filters.search, filters.include_inactive),
            to_table=_packaging_table,
            decimal_places=DECIMAL_PLACES,
            describe=lambda record: record["name"],
            open_form=lambda record: open_record_form(
                "Editar embalagem" if record else "Nova embalagem",
                lambda: _render_packaging_form(actor, record),
            ),
            delete=lambda record_id: catalog_service.delete_packaging_item(actor, record_id),
            set_active=lambda record_id, is_active: catalog_service.set_packaging_item_active(
                actor, record_id, is_active
            ),
        )
    )
