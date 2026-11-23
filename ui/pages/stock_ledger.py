from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.inventory import (
    COUNTED_REASONS,
    AdjustmentReason,
    MovementType,
    SourceModule,
    StockItemRef,
    format_quantity,
    is_whole_unit,
)
from services import inventory as inventory_service
from services.inventory import AdjustmentInput
from ui.effects import remember_effects, show_effects
from ui.feedback import show_flash
from ui.formatting import style_numbers, to_float
from ui.forms import enum_selectbox, to_decimal
from ui.labels import ADJUSTMENT_REASON_LABELS, MOVEMENT_TYPE_LABELS, SOURCE_MODULE_LABELS, STOCK_ITEM_KIND_LABELS
from ui.records import finish_action
from ui.session import get_session_user

PAGE_KEY = "stock_ledger"


def _movements_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Data": [row["movement_date"] for row in rows],
            "Tipo": [MOVEMENT_TYPE_LABELS[MovementType(row["movement_type"])] for row in rows],
            "Origem": [
                f"{SOURCE_MODULE_LABELS[SourceModule(row['source_module'])]}"
                + (f" #{row['source_id']}" if row["source_id"] else "")
                for row in rows
            ],
            "Quantidade": [to_float(row["quantity"]) for row in rows],
            "Saldo após": [to_float(row["balance_after"]) for row in rows],
            "Custo unitário (R$)": [to_float(row["unit_cost"]) for row in rows],
            "Valor (R$)": [to_float(row["total_value"]) for row in rows],
            "Motivo": [
                ADJUSTMENT_REASON_LABELS[AdjustmentReason(row["reason"])] if row["reason"] else None for row in rows
            ],
            "Observação": [row["notes"] for row in rows],
            "Usuário": [row["user_email"] for row in rows],
        }
    )


def _render_adjustment_dialog(actor: User, item: StockItemRef, label: str, current_stock: Decimal) -> None:
    whole = is_whole_unit(item.kind)
    step, number_format = (1.0, "%.0f") if whole else (0.001, "%.3f")
    st.markdown(f"**{label}** · saldo atual {format_quantity(item.kind, current_stock)}")
    reason = enum_selectbox(st, "Motivo", ADJUSTMENT_REASON_LABELS, AdjustmentReason.COUNT, f"{PAGE_KEY}_reason")
    counted_stock = lost_quantity = unit_cost = None
    if reason in COUNTED_REASONS:
        counted_stock = st.number_input(
            "Saldo contado", min_value=0.0, step=step, format=number_format, value=to_float(current_stock),
            help="O sistema calcula a diferença para o saldo atual.",
        )  # fmt: skip
    else:
        lost_quantity = st.number_input("Quantidade que saiu", min_value=0.0, step=step, format=number_format)
    if reason is AdjustmentReason.OPENING:
        unit_cost = st.number_input("Custo unitário (R$)", min_value=0.0, step=0.01, format="%.4f")
    notes = st.text_area("Observação", placeholder="Ex.: inventário de fim de mês, saca molhada na chuva", height=68)
    adjustment_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        adjustment_date = st.date_input("Data do ajuste", value=today(), max_value=today(), format="DD/MM/YYYY")
    places = 0 if whole else 3
    data = AdjustmentInput(
        item=item,
        reason=reason,
        notes=notes,
        counted_stock=to_decimal(counted_stock, places),
        lost_quantity=to_decimal(lost_quantity, places),
        unit_cost=to_decimal(unit_cost, 4),
        adjustment_date=adjustment_date,
    )
    if st.button("Registrar ajuste", type="primary", icon=":material/tune:"):
        try:
            effects = inventory_service.adjust_inventory(actor, data)
        except AppError as error:
            st.error(str(error))
        else:
            remember_effects(f"Ajuste registrado: {label}.", effects)
            finish_action(PAGE_KEY, "Ajuste de inventário registrado.")


def _select_item(actor: User) -> tuple[StockItemRef | None, date, date]:
    kind_column, item_column, period_column = st.columns([1.2, 2, 1.4], vertical_alignment="bottom")
    kind = enum_selectbox(kind_column, "Categoria", STOCK_ITEM_KIND_LABELS, None, f"{PAGE_KEY}_kind")
    items = inventory_service.list_stock_items(actor, kind)
    labels = {row["id"]: row["label"] + ("" if row["is_active"] else " (inativo)") for row in items}
    item_id = item_column.selectbox(
        "Item", list(labels), format_func=labels.get, index=None, placeholder="Selecione", key=f"{PAGE_KEY}_item_{kind}"
    )
    period = period_column.date_input(
        "Período", value=(today() - timedelta(days=30), today()), format="DD/MM/YYYY", key=f"{PAGE_KEY}_period"
    )
    start, end = period if len(period) == 2 else (period[0], period[0])
    return (StockItemRef(kind, item_id) if item_id is not None else None), start, end


def render_stock_ledger_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Extrato de estoque")
    st.caption("Todos os movimentos de um item, com o saldo após cada um. Movimentos nunca são editados ou apagados.")
    show_effects()
    item, start, end = _select_item(actor)
    if item is None:
        st.info("Escolha a categoria e o item para ver o extrato.", icon=":material/info:")
        return
    try:
        balance = inventory_service.get_stock_balance(actor, item)
        movements = inventory_service.list_item_movements(actor, item, start, end)
    except AppError as error:
        st.error(str(error))
        return
    st.markdown(f"Saldo atual de **{balance.label}**: {format_quantity(item.kind, balance.stock)}")
    if has_permission(actor, Permission.ADJUST_INVENTORY) and st.button("Ajustar estoque", icon=":material/tune:"):
        st.dialog("Ajuste de inventário")(_render_adjustment_dialog)(actor, item, balance.label, balance.stock)
    if not movements:
        st.info("Nenhum movimento no período.", icon=":material/info:")
        return
    places = 0 if is_whole_unit(item.kind) else 3
    st.dataframe(
        style_numbers(
            _movements_table(movements),
            {"Quantidade": places, "Saldo após": places, "Custo unitário (R$)": 4, "Valor (R$)": 2},
        ),
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={"Data": st.column_config.DateColumn(format="DD/MM/YYYY")},
    )
