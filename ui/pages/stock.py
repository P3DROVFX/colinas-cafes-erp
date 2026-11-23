from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.errors import AppError
from domain.inventory import StockItemKind, StockStatus, is_whole_unit, stock_status
from services import inventory as inventory_service
from ui.formatting import format_currency, style_numbers, to_float
from ui.labels import STOCK_ITEM_KIND_LABELS, STOCK_STATUS_LABELS
from ui.session import get_session_user


def _unit(kind: StockItemKind) -> str:
    return "un." if is_whole_unit(kind) else "kg"


def _positions_table(kind: StockItemKind, rows: list[dict[str, Any]]) -> pd.DataFrame:
    unit = _unit(kind)
    return pd.DataFrame(
        {
            "Item": [row["label"] for row in rows],
            f"Saldo ({unit})": [to_float(row["stock"]) for row in rows],
            f"Mínimo ({unit})": [to_float(row["min_stock"]) for row in rows],
            "Situação": [STOCK_STATUS_LABELS[stock_status(row["stock"], row["min_stock"])] for row in rows],
            "Custo médio (R$)": [to_float(row["unit_cost"]) for row in rows],
            "Valor em estoque (R$)": [to_float(row["stock"] * row["unit_cost"]) for row in rows],
            "Local": [row["location"] for row in rows],
        }
    )


def _render_positions(actor, kind: StockItemKind) -> None:
    try:
        rows = inventory_service.list_stock_positions(actor, kind)
    except AppError as error:
        st.error(str(error))
        return
    if not rows:
        st.info("Nenhum item nesta categoria.", icon=":material/info:")
        return
    total_value = sum((row["stock"] * row["unit_cost"] for row in rows), Decimal("0"))
    attention = [row for row in rows if stock_status(row["stock"], row["min_stock"]) is not StockStatus.OK]
    value_column, attention_column = st.columns(2)
    with value_column.container(border=True):
        st.metric("Valor em estoque", format_currency(total_value))
    with attention_column.container(border=True):
        st.metric("Itens zerados ou abaixo do mínimo", len(attention))
    unit = _unit(kind)
    places = 0 if is_whole_unit(kind) else 3
    st.dataframe(
        style_numbers(
            _positions_table(kind, rows),
            {f"Saldo ({unit})": places, f"Mínimo ({unit})": places, "Custo médio (R$)": 2, "Valor em estoque (R$)": 2},
        ),
        hide_index=True,
        width="stretch",
        placeholder="—",
    )


def render_stock_page() -> None:
    actor = get_session_user()
    st.title("Posição de estoque")
    st.caption("Saldo, custo médio e valor de cada item. O saldo só muda por movimentos registrados.")
    tabs = st.tabs([STOCK_ITEM_KIND_LABELS[kind] for kind in StockItemKind])
    for tab, kind in zip(tabs, StockItemKind, strict=True):
        with tab:
            _render_positions(actor, kind)
