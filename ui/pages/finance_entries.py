from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.finance import (
    MAX_RECURRENCE_MONTHS,
    EntryDisplayStatus,
    EntryType,
    ManualEntryInput,
    SettlementInput,
    SettlementMethod,
)
from domain.inventory import SourceModule
from services import finance as finance_service
from services.finance import EntryFilters
from ui.feedback import show_flash
from ui.formatting import format_currency, style_numbers, to_float
from ui.forms import enum_selectbox, record_selectbox, to_decimal
from ui.labels import ENTRY_STATUS_BADGES, ENTRY_TYPE_LABELS, SETTLEMENT_METHOD_LABELS, SOURCE_MODULE_LABELS
from ui.records import run_and_finish
from ui.session import get_session_user

PAGE_KEY = "finance_entries"
OPEN_STATUSES = (EntryDisplayStatus.PENDING, EntryDisplayStatus.OVERDUE)
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")


def _render_filters(actor: User) -> EntryFilters:
    type_column, status_column, period_column, action_column = st.columns([1, 2, 1.4, 1], vertical_alignment="bottom")
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
    if has_permission(actor, Permission.MANAGE_FINANCE) and action_column.button(
        "Novo lançamento", type="primary", icon=":material/add:", width="stretch"
    ):
        st.dialog("Novo lançamento")(_render_entry_form)(actor)
    start, end = period if len(period) == 2 else (period[0], period[0])
    return EntryFilters(start, end, entry_type, tuple(statuses or EntryDisplayStatus))


def _render_entry_form(actor: User) -> None:
    options = finance_service.get_entry_form_options(actor)
    categories = {row["id"]: row for row in options.categories}
    category_id = record_selectbox(
        st, "Categoria", options.categories, None, f"{PAGE_KEY}_category",
        lambda row: f"{row['name']} ({ENTRY_TYPE_LABELS[EntryType(row['entry_type'])].lower()})",
    )  # fmt: skip
    description = st.text_input("Descrição", placeholder="Ex.: Gás do torrador – novembro")
    left, right = st.columns(2)
    amount = left.number_input("Valor (R$)", min_value=0.0, step=10.0, format="%.2f")
    due_date = right.date_input("Vencimento", value=today(), format="DD/MM/YYYY")
    is_receivable = category_id is not None and categories[category_id]["entry_type"] == EntryType.RECEIVABLE
    counterparties = options.customers if is_receivable else options.suppliers
    counterparty_id = record_selectbox(
        st, "Cliente (opcional)" if is_receivable else "Fornecedor (opcional)", counterparties, None,
        f"{PAGE_KEY}_counterparty_{is_receivable}", lambda row: row["name"], placeholder="Nenhum",
    )  # fmt: skip
    left, right = st.columns(2)
    repeat = left.number_input(
        "Repetir por (meses)", min_value=1, max_value=MAX_RECURRENCE_MONTHS, step=1, value=1,
        help="Gera um título por mês com a mesma data, para despesas fixas como aluguel.",
    )  # fmt: skip
    accrual_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        accrual_date = right.date_input("Competência", value=today(), max_value=today(), format="DD/MM/YYYY")
    data = ManualEntryInput(
        category_id=category_id,
        description=description,
        amount=to_decimal(amount),
        due_date=due_date,
        supplier_id=None if is_receivable else counterparty_id,
        customer_id=counterparty_id if is_receivable else None,
        repeat_months=int(repeat),
    )
    if st.button("Lançar", type="primary", icon=":material/check:"):
        run_and_finish(
            PAGE_KEY,
            lambda: finance_service.create_manual_entry(actor, data, accrual_date),
            "Lançamento registrado." if repeat == 1 else f"{repeat} lançamentos registrados.",
        )


def _render_settle_dialog(actor: User, selected: list[dict[str, Any]]) -> None:
    receivable = sum((row["amount"] for row in selected if row["entry_type"] == EntryType.RECEIVABLE), Decimal("0"))
    payable = sum((row["amount"] for row in selected if row["entry_type"] == EntryType.PAYABLE), Decimal("0"))
    st.markdown(
        f"Liquidar **{len(selected)}** título(s): recebimentos de {format_currency(receivable)} e pagamentos de "
        f"{format_currency(payable)}."
    )
    accounts = [row for row in finance_service.list_account_balances(actor) if row["is_active"]]
    account_id = record_selectbox(st, "Conta", accounts, None, f"{PAGE_KEY}_account", lambda row: row["name"])
    method = enum_selectbox(st, "Forma", SETTLEMENT_METHOD_LABELS, SettlementMethod.PIX, f"{PAGE_KEY}_method")
    settled_date = st.date_input(
        "Data da liquidação", value=today(), min_value=max(row["accrual_date"] for row in selected), max_value=today(),
        format="DD/MM/YYYY",
    )  # fmt: skip
    if st.button("Liquidar", type="primary", icon=":material/payments:"):
        data = SettlementInput(tuple(row["id"] for row in selected), account_id, method, settled_date)
        run_and_finish(PAGE_KEY, lambda: finance_service.settle_entries(actor, data), "Títulos liquidados.")


def _render_cancel_dialog(actor: User, entry: dict[str, Any]) -> None:
    st.markdown(f"Cancelar **{entry['description']}** ({format_currency(entry['amount'])})?")
    reason = st.text_input("Motivo")
    if st.button("Cancelar lançamento", type="primary", icon=":material/block:"):
        run_and_finish(
            PAGE_KEY, lambda: finance_service.cancel_manual_entry(actor, entry["id"], reason), "Lançamento cancelado."
        )


def _render_reverse_dialog(actor: User, entry: dict[str, Any]) -> None:
    st.markdown(
        f"Estornar a liquidação de **{entry['description']}**? O título volta a ficar pendente e sai do saldo da conta "
        f"{entry['account_name']}."
    )
    if st.button("Estornar liquidação", type="primary", icon=":material/undo:"):
        run_and_finish(
            PAGE_KEY, lambda: finance_service.reverse_settlement(actor, entry["id"]), "Liquidação estornada."
        )


def _render_actions(actor: User, selected: list[dict[str, Any]]) -> None:
    pending = [row for row in selected if row["status"] == "PENDING"]
    with st.container(horizontal=True):
        if (
            has_permission(actor, Permission.MANAGE_FINANCE)
            and pending
            and st.button(f"Liquidar {len(pending)} selecionado(s)", type="primary", icon=":material/payments:")
        ):
            st.dialog("Liquidar títulos")(_render_settle_dialog)(actor, pending)
        if len(selected) != 1:
            return
        entry = selected[0]
        is_manual = SourceModule(entry["source_module"]) is SourceModule.MANUAL
        can_cancel = is_manual and entry["status"] == "PENDING" and has_permission(actor, Permission.MANAGE_FINANCE)
        if can_cancel and st.button("Cancelar lançamento", icon=":material/block:"):
            st.dialog("Cancelar lançamento")(_render_cancel_dialog)(actor, entry)
        can_reverse = entry["status"] == "SETTLED" and has_permission(actor, Permission.REVERSE_SETTLEMENTS)
        reconciled_help = "Desfaça a conciliação antes." if entry["is_reconciled"] else None
        if can_reverse and st.button(
            "Estornar liquidação", icon=":material/undo:", disabled=entry["is_reconciled"], help=reconciled_help
        ):
            st.dialog("Estornar liquidação")(_render_reverse_dialog)(actor, entry)


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
            "Valor (R$)": [to_float(row["amount"]) for row in entries],
            "Situação": [ENTRY_STATUS_BADGES[EntryDisplayStatus(row["display_status"])][0] for row in entries],
            "Liquidado em": [row["settled_date"] for row in entries],
            "Conta": [row["account_name"] for row in entries],
            "Origem": [SOURCE_MODULE_LABELS[SourceModule(row["source_module"])] for row in entries],
        }
    )


def render_finance_entries_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Contas a pagar e a receber")
    st.caption(
        "Títulos gerados pelas compras, colheitas, vendas e lançamentos manuais. Vencido é um título pendente após o "
        "prazo. Selecione títulos para liquidar."
    )
    filters = _render_filters(actor)
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
    version = st.session_state.get(f"{PAGE_KEY}_table_version", 0)
    event = st.dataframe(
        style_numbers(_entries_table(entries), {"Valor (R$)": 2}),
        hide_index=True,
        width="stretch",
        placeholder="—",
        on_select="rerun",
        selection_mode="multi-row",
        column_config={"Vencimento": DATE_COLUMN, "Liquidado em": DATE_COLUMN},
        key=f"{PAGE_KEY}_table_{version}",
    )
    selected = [entries[index] for index in event.selection.rows if index < len(entries)]
    if selected:
        _render_actions(actor, selected)
    else:
        st.caption("Selecione um ou mais títulos para liquidar, estornar ou cancelar.")
