from datetime import date

import pandas as pd
import streamlit as st

from domain.access import Permission, User, has_permission
from domain.finance import (
    AccountKind,
    DreGroup,
    EntryType,
    FinancialAccountInput,
    FinancialCategoryInput,
    dre_groups_for,
)
from services import finance_setup as finance_setup_service
from ui.feedback import show_flash
from ui.formatting import to_float
from ui.forms import enum_selectbox, form_key, to_decimal
from ui.labels import ACCOUNT_KIND_LABELS, ACTIVE_LABELS, DRE_GROUP_LABELS, ENTRY_TYPE_LABELS
from ui.records import Record, RecordList, open_record_form, render_record_list, render_save_button
from ui.session import get_session_user

CATEGORIES_KEY = "financial_categories"
ACCOUNTS_KEY = "financial_accounts"
SYSTEM_LABELS = {True: "Sistema", False: "Personalizada"}

ACCOUNT_COLUMN_CONFIG = {"Data do saldo": st.column_config.DateColumn(format="DD/MM/YYYY")}
ACCOUNT_DECIMAL_PLACES = {"Saldo inicial (R$)": 2}


def _categories_table(categories: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [row["name"] for row in categories],
            "Tipo": [ENTRY_TYPE_LABELS[EntryType(row["entry_type"])] for row in categories],
            "Grupo da DRE": [DRE_GROUP_LABELS[DreGroup(row["dre_group"])] for row in categories],
            "Origem": [SYSTEM_LABELS[row["is_system"]] for row in categories],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in categories],
        }
    )


def _accounts_table(accounts: list[Record]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [row["name"] for row in accounts],
            "Tipo": [ACCOUNT_KIND_LABELS[AccountKind(row["kind"])] for row in accounts],
            "Saldo inicial (R$)": [to_float(row["opening_balance"]) for row in accounts],
            "Data do saldo": [row["opening_date"] for row in accounts],
            "Origem": [SYSTEM_LABELS[row["is_system"]] for row in accounts],
            "Situação": [ACTIVE_LABELS[row["is_active"]] for row in accounts],
        }
    )


def _render_category_form(actor: User, record: Record | None) -> None:
    key = form_key(CATEGORIES_KEY, record)
    record = record or {}
    name = st.text_input("Nome", value=record.get("name", ""), key=f"{key}_name")
    left, right = st.columns(2)
    entry_type = enum_selectbox(left, "Tipo", ENTRY_TYPE_LABELS, record.get("entry_type"), f"{key}_entry_type")
    groups = {group: DRE_GROUP_LABELS[group] for group in dre_groups_for(entry_type)}
    dre_group = enum_selectbox(right, "Grupo da DRE", groups, record.get("dre_group"), f"{key}_dre_group")
    data = FinancialCategoryInput(name, entry_type, dre_group)
    render_save_button(
        CATEGORIES_KEY,
        record or None,
        "Cadastrar categoria",
        lambda: finance_setup_service.create_financial_category(actor, data),
        lambda category_id: finance_setup_service.update_financial_category(actor, category_id, data),
        f"Categoria cadastrada: {data.name}.",
        f"Categoria atualizada: {data.name}.",
    )


def _render_account_form(actor: User, record: Record | None) -> None:
    key = form_key(ACCOUNTS_KEY, record)
    record = record or {}
    left, right = st.columns(2)
    name = left.text_input("Nome", value=record.get("name", ""), key=f"{key}_name")
    kind = enum_selectbox(
        right, "Tipo", ACCOUNT_KIND_LABELS, record.get("kind"), f"{key}_kind", disabled=record.get("is_system", False)
    )
    opening_balance = left.number_input(
        "Saldo inicial (R$)",
        step=100.0,
        format="%.2f",
        value=to_float(record.get("opening_balance")) or 0.0,
        key=f"{key}_opening_balance",
    )
    opening_date = right.date_input(
        "Data do saldo inicial",
        value=record.get("opening_date", date.today()),
        max_value=date.today(),
        format="DD/MM/YYYY",
        key=f"{key}_opening_date",
    )
    data = FinancialAccountInput(name, kind, to_decimal(opening_balance), opening_date)
    render_save_button(
        ACCOUNTS_KEY,
        record or None,
        "Cadastrar conta",
        lambda: finance_setup_service.create_financial_account(actor, data),
        lambda account_id: finance_setup_service.update_financial_account(actor, account_id, data),
        f"Conta cadastrada: {data.name}.",
        f"Conta atualizada: {data.name}.",
    )


def _categories_list(actor: User, can_write: bool) -> RecordList:
    return RecordList(
        key=CATEGORIES_KEY,
        noun="categoria",
        new_label="Nova categoria",
        search_placeholder="Buscar categoria",
        empty_message="Nenhuma categoria cadastrada.",
        can_write=can_write,
        load=lambda filters: finance_setup_service.list_financial_categories(
            actor, filters.search, filters.include_inactive
        ),
        to_table=_categories_table,
        describe=lambda record: record["name"],
        open_form=lambda record: open_record_form(
            "Editar categoria" if record else "Nova categoria",
            lambda: _render_category_form(actor, record),
        ),
        delete=lambda record_id: finance_setup_service.delete_financial_category(actor, record_id),
        set_active=lambda record_id, is_active: finance_setup_service.set_financial_category_active(
            actor, record_id, is_active
        ),
        can_edit=lambda record: not record["is_system"],
    )


def _accounts_list(actor: User, can_write: bool) -> RecordList:
    return RecordList(
        key=ACCOUNTS_KEY,
        noun="conta",
        new_label="Nova conta",
        search_placeholder="Buscar conta",
        empty_message="Nenhuma conta cadastrada.",
        can_write=can_write,
        load=lambda filters: finance_setup_service.list_financial_accounts(
            actor, filters.search, filters.include_inactive
        ),
        to_table=_accounts_table,
        column_config=ACCOUNT_COLUMN_CONFIG,
        decimal_places=ACCOUNT_DECIMAL_PLACES,
        describe=lambda record: record["name"],
        open_form=lambda record: open_record_form(
            "Editar conta" if record else "Nova conta",
            lambda: _render_account_form(actor, record),
        ),
        delete=lambda record_id: finance_setup_service.delete_financial_account(actor, record_id),
        set_active=lambda record_id, is_active: finance_setup_service.set_financial_account_active(
            actor, record_id, is_active
        ),
    )


def render_finance_setup_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Categorias e contas")
    st.caption("Categorias classificam os títulos na DRE; contas são o caixa e o banco usados nas liquidações.")
    can_write = has_permission(actor, Permission.MANAGE_FINANCE_SETUP)
    categories_tab, accounts_tab = st.tabs(["Categorias", "Contas"])
    with categories_tab:
        render_record_list(_categories_list(actor, can_write))
    with accounts_tab:
        render_record_list(_accounts_list(actor, can_write))
