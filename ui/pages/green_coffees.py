from datetime import date

import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.catalog import FIRST_HARVEST_YEAR, LAST_HARVEST_YEAR, GreenCoffeeInput, Process
from services import catalog as catalog_service
from ui.feedback import show_flash
from ui.formatting import to_float
from ui.forms import enum_selectbox, form_key, record_selectbox, to_decimal
from ui.labels import ACTIVE_LABELS, PROCESS_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

PAGE_KEY = "green_coffees"

DECIMAL_PLACES = {"SCA": 2, "Estoque (kg)": 3, "Mínimo (kg)": 3, "Custo médio (R$/kg)": 2}


def _green_coffees_table(coffees: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Código": [row["code"] for row in coffees],
            "Nome": [row["name"] for row in coffees],
            "Fazenda": [row["farm_name"] for row in coffees],
            "Varietal": [row["variety"] for row in coffees],
            "Processo": [PROCESS_LABELS[Process(row["process"])] for row in coffees],
            "Safra": [str(row["harvest_year"]) for row in coffees],
            "SCA": [to_float(row["sca_score"]) for row in coffees],
            "Estoque (kg)": [to_float(row["stock_kg"]) for row in coffees],
            "Mínimo (kg)": [to_float(row["min_stock_kg"]) for row in coffees],
            "Custo médio (R$/kg)": [to_float(row["avg_cost_per_kg"]) for row in coffees],
            "Local": [row["location"] for row in coffees],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in coffees],
        }
    )


def _render_green_coffee_form(actor: User, record: Record | None) -> None:
    key = form_key(PAGE_KEY, record)
    record = record or {}
    is_editing = bool(record)
    if is_editing:
        st.caption("Código, fazenda, varietal, processo e safra identificam o lote e não mudam depois do cadastro.")
    left, right = st.columns(2)
    farm_id = record_selectbox(
        left,
        "Fazenda de origem",
        catalog_service.list_farm_options(actor, record.get("farm_id")),
        record.get("farm_id"),
        f"{key}_farm",
        lambda farm: f"{farm['name']} ({'própria' if farm['is_own'] else 'parceira'})",
        disabled=is_editing,
    )
    code = right.text_input(
        "Código",
        value=record.get("code", ""),
        max_chars=10,
        key=f"{key}_code",
        disabled=is_editing,
        help="Curto, sem espaços. Entra no SKU dos produtos (ex.: BVCAT).",
    )
    name = left.text_input("Nome comercial", value=record.get("name", ""), key=f"{key}_name")
    variety = right.text_input("Varietal", value=record.get("variety", ""), key=f"{key}_variety", disabled=is_editing)
    process = enum_selectbox(
        left, "Processo", PROCESS_LABELS, record.get("process"), f"{key}_process", disabled=is_editing
    )
    harvest_year = right.number_input(
        "Safra",
        min_value=FIRST_HARVEST_YEAR,
        max_value=LAST_HARVEST_YEAR,
        step=1,
        value=record.get("harvest_year", date.today().year),
        key=f"{key}_harvest_year",
        disabled=is_editing,
    )
    sca_score = left.number_input(
        "Pontuação SCA",
        min_value=60.0,
        max_value=100.0,
        step=0.25,
        format="%.2f",
        value=to_float(record.get("sca_score")),
        key=f"{key}_sca",
    )
    moisture_pct = right.number_input(
        "Umidade (%)",
        min_value=0.0,
        max_value=20.0,
        step=0.1,
        format="%.1f",
        value=to_float(record.get("moisture_pct")),
        key=f"{key}_moisture",
    )
    min_stock_kg = left.number_input(
        "Estoque mínimo (kg)",
        min_value=0.0,
        step=1.0,
        format="%.3f",
        value=to_float(record.get("min_stock_kg")) or 0.0,
        key=f"{key}_min_stock",
    )
    location = right.text_input("Localização no armazém", value=record.get("location") or "", key=f"{key}_location")
    data = GreenCoffeeInput(
        code,
        name,
        farm_id,
        variety,
        process,
        int(harvest_year),
        to_decimal(sca_score),
        to_decimal(moisture_pct, 1),
        to_decimal(min_stock_kg, 3),
        location,
    )
    render_save_button(
        PAGE_KEY,
        record or None,
        "Cadastrar café verde",
        lambda: catalog_service.create_green_coffee(actor, data),
        lambda green_coffee_id: catalog_service.update_green_coffee(actor, green_coffee_id, data),
        f"Café verde cadastrado: {data.name}.",
        f"Café verde atualizado: {data.name}.",
    )


def render_green_coffees_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Cafés verdes")
    st.caption(
        "Cada lote de origem (fazenda, varietal, processo e safra). Estoque e custo médio vêm das compras e colheitas."
    )
    render_record_list(
        RecordList(
            key=PAGE_KEY,
            noun="café verde",
            new_label="Novo café verde",
            search_placeholder="Buscar por código, nome, varietal ou fazenda",
            empty_message="Nenhum café verde cadastrado. Cadastre a fazenda e depois o café.",
            can_write=has_permission(actor, Permission.MANAGE_CATALOG),
            load=lambda filters: catalog_service.list_green_coffees(actor, filters.search, filters.include_inactive),
            to_table=_green_coffees_table,
            decimal_places=DECIMAL_PLACES,
            describe=lambda record: f"{record['code']} · {record['name']}",
            open_form=lambda record: open_record_form(
                "Editar café verde" if record else "Novo café verde",
                lambda: _render_green_coffee_form(actor, record),
            ),
            delete=lambda record_id: catalog_service.delete_green_coffee(actor, record_id),
            set_active=lambda record_id, is_active: catalog_service.set_green_coffee_active(
                actor, record_id, is_active
            ),
        )
    )
