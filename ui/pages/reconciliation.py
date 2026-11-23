from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.finance import EntryType
from services import finance as finance_service
from ui.feedback import show_flash
from ui.filters import period_input
from ui.formatting import format_currency, style_numbers, to_float
from ui.forms import record_selectbox
from ui.labels import ENTRY_TYPE_LABELS, SETTLEMENT_METHOD_LABELS
from ui.records import run_and_finish
from ui.session import get_session_user

PAGE_KEY = "reconciliation"
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")


def _signed(row: dict[str, Any]) -> float:
    amount = to_float(row["amount"])
    return amount if row["entry_type"] == EntryType.RECEIVABLE else -amount


def _entries_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Liquidado em": [row["settled_date"] for row in rows],
            "Descrição": [row["description"] for row in rows],
            "Tipo": [ENTRY_TYPE_LABELS[EntryType(row["entry_type"])] for row in rows],
            "Forma": [SETTLEMENT_METHOD_LABELS.get(row["settlement_method"], row["settlement_method"]) for row in rows],
            "Valor (R$)": [_signed(row) for row in rows],
            "Conciliado em": [row["reconciled_date"] for row in rows],
        }
    )


def _render_balances(actor: User, account_id: int) -> None:
    [account] = [row for row in finance_service.list_account_balances(actor) if row["id"] == account_id]
    columns = st.columns(3)
    columns[0].metric("Saldo pelo sistema", format_currency(account["system_balance"]))
    columns[1].metric("Saldo conciliado", format_currency(account["reconciled_balance"]))
    columns[2].metric("Lançamentos a conciliar", account["unreconciled_count"])
    if account["system_balance"] == account["reconciled_balance"]:
        st.success("Saldo conciliado igual ao saldo do sistema.", icon=":material/check_circle:")


def render_reconciliation_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Conciliação")
    st.caption(
        "Confira os títulos liquidados com o extrato do banco ou a contagem do caixa e marque os que batem. "
        "Título conciliado não pode ter a liquidação estornada."
    )
    try:
        accounts = finance_service.list_account_balances(actor)
    except AppError as error:
        st.error(str(error))
        return
    account_column, period_column, status_column = st.columns([1.4, 1.4, 1.2], vertical_alignment="bottom")
    account_id = record_selectbox(
        account_column, "Conta", accounts, accounts[0]["id"] if accounts else None, f"{PAGE_KEY}_account",
        lambda row: row["name"],
    )  # fmt: skip
    if account_id is None:
        st.info("Cadastre uma conta financeira.", icon=":material/info:")
        return
    start, end = period_input(period_column, "Liquidados entre", f"{PAGE_KEY}_period", 30)
    pending_only = status_column.toggle("Só os não conciliados", value=True, key=f"{PAGE_KEY}_pending")
    _render_balances(actor, account_id)
    try:
        rows = finance_service.list_reconciliation(actor, account_id, start, end)
    except AppError as error:
        st.error(str(error))
        return
    if pending_only:
        rows = [row for row in rows if not row["is_reconciled"]]
    if not rows:
        st.info("Nenhum título liquidado para conferir neste período.", icon=":material/info:")
        return
    version = st.session_state.get(f"{PAGE_KEY}_table_version", 0)
    event = st.dataframe(
        style_numbers(_entries_table(rows), {"Valor (R$)": 2}),
        hide_index=True,
        width="stretch",
        placeholder="—",
        on_select="rerun",
        selection_mode="multi-row",
        column_config={"Liquidado em": DATE_COLUMN, "Conciliado em": DATE_COLUMN},
        key=f"{PAGE_KEY}_table_{version}",
    )
    selected = [rows[index] for index in event.selection.rows if index < len(rows)]
    if not has_permission(actor, Permission.MANAGE_FINANCE):
        return
    if not selected:
        st.caption("Selecione os títulos que conferem com o extrato.")
        return
    ids = [row["id"] for row in selected]
    with st.container(horizontal=True):
        if st.button(f"Conciliar {len(ids)} título(s)", type="primary", icon=":material/fact_check:"):
            run_and_finish(
                PAGE_KEY, lambda: finance_service.set_reconciled(actor, ids, True, today()), "Títulos conciliados."
            )
        if any(row["is_reconciled"] for row in selected) and st.button("Desfazer conciliação", icon=":material/undo:"):
            run_and_finish(PAGE_KEY, lambda: finance_service.set_reconciled(actor, ids, False), "Conciliação desfeita.")
