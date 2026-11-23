import streamlit as st

from domain.effects import EntryChange, OperationEffects, StockChange
from domain.finance import EntryType
from domain.inventory import format_quantity
from ui.formatting import format_currency

EFFECTS_KEY = "operation_effects"
ENTRY_TYPE_NAMES = {EntryType.PAYABLE: "A pagar", EntryType.RECEIVABLE: "A receber"}


def remember_effects(title: str, effects: OperationEffects) -> None:
    st.session_state[EFFECTS_KEY] = (title, effects)


def _stock_line(change: StockChange) -> str:
    before = format_quantity(change.kind, change.before)
    after = format_quantity(change.kind, change.after)
    return f"{change.label}: {before} → **{after}** · custo {format_currency(change.unit_cost)}"


def _entry_line(entry: EntryChange) -> str:
    verb = "cancelado" if entry.action == "cancelled" else f"vence {entry.due_date:%d/%m/%Y}"
    return f"{ENTRY_TYPE_NAMES[entry.entry_type]} {format_currency(entry.amount)} · {entry.description} · {verb}"


def show_effects() -> None:
    remembered = st.session_state.pop(EFFECTS_KEY, None)
    if remembered is None:
        return
    title, effects = remembered
    with st.container(border=True):
        st.success(title, icon=":material/check_circle:")
        stock_column, finance_column = st.columns(2)
        with stock_column:
            st.markdown("**Estoque**")
            for change in effects.stock:
                st.markdown(f"- {_stock_line(change)}")
            if not effects.stock:
                st.caption("Sem efeito no estoque.")
        with finance_column:
            st.markdown("**Financeiro**")
            for entry in effects.entries:
                st.markdown(f"- {_entry_line(entry)}")
            if not effects.entries:
                st.caption("Sem efeito no financeiro.")
