import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.brazil import PersonType
from domain.partners import SupplierInput, SupplyType
from services import partners as partners_service
from ui.feedback import show_flash
from ui.formatting import format_document, format_place
from ui.forms import enum_selectbox, form_key, state_selectbox
from ui.labels import ACTIVE_LABELS, PERSON_TYPE_LABELS, SUPPLY_TYPE_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

PAGE_KEY = "suppliers"


def _suppliers_table(suppliers: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [row["name"] for row in suppliers],
            "Fornece": [SUPPLY_TYPE_LABELS[SupplyType(row["supply_type"])] for row in suppliers],
            "CPF/CNPJ": [format_document(row["document"]) for row in suppliers],
            "Cidade": [format_place(row["city"], row["state"]) for row in suppliers],
            "E-mail": [row["email"] for row in suppliers],
            "Telefone": [row["phone"] for row in suppliers],
            "Prazo de entrega (dias)": [row["lead_time_days"] for row in suppliers],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in suppliers],
        }
    )


def _render_supplier_form(actor: User, record: Record | None) -> None:
    key = form_key(PAGE_KEY, record)
    record = record or {}
    left, right = st.columns(2)
    name = left.text_input("Nome ou razão social", value=record.get("name", ""), key=f"{key}_name")
    supply_type = enum_selectbox(right, "Fornece", SUPPLY_TYPE_LABELS, record.get("supply_type"), f"{key}_supply")
    person_type = enum_selectbox(left, "Tipo de pessoa", PERSON_TYPE_LABELS, record.get("person_type"), f"{key}_person")
    document = right.text_input(
        "CPF" if person_type is PersonType.INDIVIDUAL else "CNPJ",
        value=format_document(record.get("document")),
        key=f"{key}_document",
        help="Pequenos produtores costumam vender como pessoa física (CPF).",
    )
    email = left.text_input("E-mail", value=record.get("email") or "", key=f"{key}_email")
    phone = right.text_input("Telefone", value=record.get("phone") or "", key=f"{key}_phone")
    city = left.text_input("Cidade", value=record.get("city") or "", key=f"{key}_city")
    state = state_selectbox(right, record.get("state"), f"{key}_state")
    lead_time_days = left.number_input(
        "Prazo médio de entrega (dias)",
        min_value=0,
        step=1,
        value=record.get("lead_time_days", 7),
        key=f"{key}_lead_time",
    )
    data = SupplierInput(name, person_type, document, supply_type, email, phone, city, state, int(lead_time_days))
    render_save_button(
        PAGE_KEY,
        record or None,
        "Cadastrar fornecedor",
        lambda: partners_service.create_supplier(actor, data),
        lambda supplier_id: partners_service.update_supplier(actor, supplier_id, data),
        f"Fornecedor cadastrado: {data.name}.",
        f"Fornecedor atualizado: {data.name}.",
    )


def render_suppliers_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Fornecedores")
    st.caption("Quem fornece café verde, embalagens e serviços. Fazendas parceiras faturam por meio de um fornecedor.")
    render_record_list(
        RecordList(
            key=PAGE_KEY,
            noun="fornecedor",
            new_label="Novo fornecedor",
            search_placeholder="Buscar por nome, CPF/CNPJ ou cidade",
            empty_message="Nenhum fornecedor cadastrado. Use Novo fornecedor para cadastrar o primeiro.",
            can_write=has_permission(actor, Permission.MANAGE_SUPPLIERS),
            load=lambda filters: partners_service.list_suppliers(actor, filters.search, filters.include_inactive),
            to_table=_suppliers_table,
            describe=lambda record: record["name"],
            open_form=lambda record: open_record_form(
                "Editar fornecedor" if record else "Novo fornecedor",
                lambda: _render_supplier_form(actor, record),
            ),
            delete=lambda record_id: partners_service.delete_supplier(actor, record_id),
            set_active=lambda record_id, is_active: partners_service.set_supplier_active(actor, record_id, is_active),
        )
    )
