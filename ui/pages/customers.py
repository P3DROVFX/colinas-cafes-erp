import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.brazil import PersonType
from domain.partners import CustomerInput, Segment
from services import partners as partners_service
from ui.feedback import show_flash
from ui.formatting import format_document, format_place, to_float
from ui.forms import enum_selectbox, form_key, state_selectbox, to_decimal
from ui.labels import ACTIVE_LABELS, SEGMENT_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

PAGE_KEY = "customers"
PERSON_TYPE_SHORT_LABELS = {PersonType.INDIVIDUAL: "Pessoa física (CPF)", PersonType.COMPANY: "Pessoa jurídica (CNPJ)"}

DECIMAL_PLACES = {"Limite de crédito (R$)": 2}


def _customers_table(customers: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [row["name"] for row in customers],
            "Segmento": [SEGMENT_LABELS[Segment(row["segment"])] for row in customers],
            "CPF/CNPJ": [format_document(row["document"]) for row in customers],
            "Cidade": [format_place(row["city"], row["state"]) for row in customers],
            "E-mail": [row["email"] for row in customers],
            "Telefone": [row["phone"] for row in customers],
            "Prazo (dias)": [row["payment_term_days"] for row in customers],
            "Limite de crédito (R$)": [to_float(row["credit_limit"]) for row in customers],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in customers],
        }
    )


def _render_customer_form(actor: User, record: Record | None) -> None:
    key = form_key(PAGE_KEY, record)
    record = record or {}
    left, right = st.columns(2)
    name = left.text_input("Nome ou razão social", value=record.get("name", ""), key=f"{key}_name")
    segment = enum_selectbox(right, "Segmento", SEGMENT_LABELS, record.get("segment"), f"{key}_segment")
    person_type = enum_selectbox(
        left, "Tipo de pessoa", PERSON_TYPE_SHORT_LABELS, record.get("person_type"), f"{key}_person"
    )
    document = right.text_input(
        "CPF (opcional)" if person_type is PersonType.INDIVIDUAL else "CNPJ",
        value=format_document(record.get("document")),
        key=f"{key}_document",
    )
    if segment is not Segment.CONSUMER:
        st.caption("Cafeterias, restaurantes, empórios e empresas compram no atacado e precisam de CNPJ.")
    email = left.text_input("E-mail", value=record.get("email") or "", key=f"{key}_email")
    phone = right.text_input("Telefone", value=record.get("phone") or "", key=f"{key}_phone")
    address = st.text_input("Endereço", value=record.get("address") or "", key=f"{key}_address")
    left, right = st.columns(2)
    city = left.text_input("Cidade", value=record.get("city") or "", key=f"{key}_city")
    state = state_selectbox(right, record.get("state"), f"{key}_state")
    payment_term_days = left.number_input(
        "Prazo de pagamento (dias)",
        min_value=0,
        max_value=90,
        step=1,
        value=record.get("payment_term_days", 0),
        key=f"{key}_term",
        help="Usado nas vendas por boleto.",
    )
    credit_limit = right.number_input(
        "Limite de crédito (R$)",
        min_value=0.0,
        step=100.0,
        format="%.2f",
        value=to_float(record.get("credit_limit")) or 0.0,
        key=f"{key}_credit",
        help="Soma máxima de títulos em aberto para vender por boleto.",
    )
    data = CustomerInput(
        name,
        person_type,
        segment,
        document,
        email,
        phone,
        address,
        city,
        state,
        int(payment_term_days),
        to_decimal(credit_limit),
    )
    render_save_button(
        PAGE_KEY,
        record or None,
        "Cadastrar cliente",
        lambda: partners_service.create_customer(actor, data),
        lambda customer_id: partners_service.update_customer(actor, customer_id, data),
        f"Cliente cadastrado: {data.name}.",
        f"Cliente atualizado: {data.name}.",
    )


def render_customers_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Clientes")
    st.caption("Consumidores e clientes de atacado. Vendas de balcão sem identificação usam o Consumidor Final.")
    render_record_list(
        RecordList(
            key=PAGE_KEY,
            noun="cliente",
            new_label="Novo cliente",
            search_placeholder="Buscar por nome, CPF/CNPJ, e-mail ou cidade",
            empty_message="Nenhum cliente cadastrado. Use Novo cliente para cadastrar o primeiro.",
            can_write=has_permission(actor, Permission.MANAGE_CUSTOMERS),
            load=lambda filters: partners_service.list_customers(actor, filters.search, filters.include_inactive),
            to_table=_customers_table,
            decimal_places=DECIMAL_PLACES,
            describe=lambda record: record["name"],
            open_form=lambda record: open_record_form(
                "Editar cliente" if record else "Novo cliente",
                lambda: _render_customer_form(actor, record),
            ),
            delete=lambda record_id: partners_service.delete_customer(actor, record_id),
            set_active=lambda record_id, is_active: partners_service.set_customer_active(actor, record_id, is_active),
        )
    )
