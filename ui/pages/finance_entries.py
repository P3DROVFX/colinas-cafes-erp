from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.finance import EntryDisplayStatus, EntryType
from domain.inventory import SourceModule
from services import finance as finance_service
from services.finance import EntryFilters
from ui.formatting import format_currency, style_numbers, to_float
from ui.labels import ENTRY_STATUS_BADGES, ENTRY_TYPE_LABELS, SOURCE_MODULE_LABELS
from ui.session import get_session_user

PAGE_KEY = "finance_entries"
OPEN_STATUSES = (EntryDisplayStatus.PENDING, EntryDisplayStatus.OVERDUE)


def _render_filters() -> EntryFilters:
    type_column, status_column, period_column = st.columns([1, 2, 1.4], vertical_alignment="bottom")
    entry_type = type_column.segmented_control(
        "Tipo", list(EntryType), format_func=ENTRY_TYPE_LABELS.get, key=f"{PAGE_KEY}_type"
    )
    statuses = status_column.multiselect(
        "Situação",
        list(EntryDisplayStatus),
        default=list(OPEN_STATUSES),
        format_func=lambda status: ENTRY_STATUS_BADGES[status][0],
        key=f"{PAGE_KEY}_statuses",
    )
    period = period_column.date_input(
        "Vencimento",
        value=(today() - timedelta(days=60), today() + timedelta(days=120)),
        format="DD/MM/YYYY",
        key=f"{PAGE_KEY}_period",
    )
    start, end = period if len(period) == 2 else (period[0], period[0])
    return EntryFilters(start, end, entry_type, tuple(statuses or EntryDisplayStatus))


def _total(entries: list[dict[str, Any]], entry_type: EntryType, statuses: tuple[EntryDisplayStatus, ...]) -> Decimal:
    return sum(
        (row["amount"] for row in entries if row["entry_type"] == entry_type and row["display_status"] in statuses),
        Decimal("0"),
    )


def _entries_table(entries: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Vencimento": [row["due_date"] for row in entries],
            "Tipo": [ENTRY_TYPE_LABELS[EntryType(row["entry_type"])] for row in entries],
            "Descrição": [row["description"] for row in entries],
            "Categoria": [row["category_name"] for row in entries],
            "Fornecedor ou cliente": [row["counterparty"] for row in entries],
            "Parcela": [f"{row['installment']}/{row['installment_count']}" for row in entries],
            "Valor (R$)": [to_float(row["amount"]) for row in entries],
            "Situação": [ENTRY_STATUS_BADGES[EntryDisplayStatus(row["display_status"])][0] for row in entries],
            "Origem": [SOURCE_MODULE_LABELS[SourceModule(row["source_module"])] for row in entries],
        }
    )


def render_finance_entries_page() -> None:
    actor = get_session_user()
    st.title("Contas a pagar e a receber")
    st.caption(
        "Títulos gerados pelas compras, vendas e lançamentos manuais. Vencido é um título pendente após o prazo."
    )
    filters = _render_filters()
    try:
        entries = finance_service.list_entries(actor, filters)
    except AppError as error:
        st.error(str(error))
        return
    payable_column, receivable_column, overdue_column = st.columns(3)
    with payable_column.container(border=True):
        st.metric("A pagar em aberto", format_currency(_total(entries, EntryType.PAYABLE, OPEN_STATUSES)))
    with receivable_column.container(border=True):
        st.metric("A receber em aberto", format_currency(_total(entries, EntryType.RECEIVABLE, OPEN_STATUSES)))
    with overdue_column.container(border=True):
        overdue = [row for row in entries if row["display_status"] == EntryDisplayStatus.OVERDUE]
        st.metric("Títulos vencidos", len(overdue))
    if not entries:
        st.info("Nenhum título com estes filtros.", icon=":material/info:")
        return
    st.dataframe(
        style_numbers(_entries_table(entries), {"Valor (R$)": 2}),
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={"Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY")},
    )
    st.caption("Liquidação, despesas manuais e fluxo de caixa chegam na próxima fase do financeiro.")
