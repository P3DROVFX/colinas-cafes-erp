import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.catalog import FarmInput
from domain.partners import SupplyType
from services import catalog as catalog_service
from services import partners as partners_service
from ui.feedback import show_flash
from ui.formatting import format_place
from ui.forms import form_key, record_selectbox, state_selectbox
from ui.labels import ACTIVE_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

PAGE_KEY = "farms"
OWNERSHIP_LABELS = {True: "Própria", False: "Parceira"}


def _farms_table(farms: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [row["name"] for row in farms],
            "Tipo": [OWNERSHIP_LABELS[row["is_own"]] for row in farms],
            "Produtor": [row["producer"] for row in farms],
            "Município": [format_place(row["city"], row["state"]) for row in farms],
            "Altitude (m)": [row["altitude_m"] for row in farms],
            "Fornecedor": [row["supplier_name"] or "—" for row in farms],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in farms],
        }
    )


def _render_farm_form(actor: User, record: Record | None) -> None:
    key = form_key(PAGE_KEY, record)
    record = record or {}
    is_own = st.segmented_control(
        "Tipo de fazenda",
        [True, False],
        default=record.get("is_own", False),
        format_func=OWNERSHIP_LABELS.get,
        required=True,
        key=f"{key}_is_own",
        disabled=bool(record),
        help="A fazenda própria abastece o estoque pela colheita; a parceira, pela compra.",
    )
    left, right = st.columns(2)
    name = left.text_input("Nome da fazenda", value=record.get("name", ""), key=f"{key}_name")
    producer = right.text_input("Produtor responsável", value=record.get("producer", ""), key=f"{key}_producer")
    city = left.text_input("Município", value=record.get("city", ""), key=f"{key}_city")
    state = state_selectbox(right, record.get("state"), f"{key}_state")
    altitude_m = left.number_input(
        "Altitude (m)", min_value=0, max_value=3000, step=10, value=record.get("altitude_m"), key=f"{key}_altitude"
    )
    supplier_id = None
    if not is_own:
        suppliers = partners_service.list_supplier_options(actor, SupplyType.GREEN_COFFEE, record.get("supplier_id"))
        supplier_id = record_selectbox(
            right,
            "Fornecedor que fatura o café",
            suppliers,
            record.get("supplier_id"),
            f"{key}_supplier",
            lambda supplier: supplier["name"],
        )
        if not suppliers:
            st.caption("Cadastre antes um fornecedor de café verde na página Fornecedores.")
    data = FarmInput(
        name, city, state, producer, bool(is_own), supplier_id, int(altitude_m) if altitude_m is not None else None
    )
    render_save_button(
        PAGE_KEY,
        record or None,
        "Cadastrar fazenda",
        lambda: catalog_service.create_farm(actor, data),
        lambda farm_id: catalog_service.update_farm(actor, farm_id, data),
        f"Fazenda cadastrada: {data.name}.",
        f"Fazenda atualizada: {data.name}.",
    )


def render_farms_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Fazendas")
    st.caption("Origem de cada café verde: a fazenda própria da família e as fazendas parceiras da região.")
    render_record_list(
        RecordList(
            key=PAGE_KEY,
            noun="fazenda",
            new_label="Nova fazenda",
            search_placeholder="Buscar por nome, produtor ou município",
            empty_message="Nenhuma fazenda cadastrada. Use Nova fazenda para cadastrar a primeira.",
            can_write=has_permission(actor, Permission.MANAGE_CATALOG),
            load=lambda filters: catalog_service.list_farms(actor, filters.search, filters.include_inactive),
            to_table=_farms_table,
            describe=lambda record: record["name"],
            open_form=lambda record: open_record_form(
                "Editar fazenda" if record else "Nova fazenda",
                lambda: _render_farm_form(actor, record),
            ),
            delete=lambda record_id: catalog_service.delete_farm(actor, record_id),
            set_active=lambda record_id, is_active: catalog_service.set_farm_active(actor, record_id, is_active),
        )
    )
