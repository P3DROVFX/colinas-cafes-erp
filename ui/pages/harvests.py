from datetime import timedelta
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.finance import EntryDisplayStatus
from domain.numbers import format_decimal
from domain.production import HARVEST_DEFAULT_TERM_DAYS, HarvestInput, harvest_unit_cost
from services import production as production_service
from services.production import PeriodFilters
from ui.effects import remember_effects, show_effects
from ui.feedback import show_flash
from ui.filters import period_input
from ui.formatting import format_currency, style_numbers, to_float
from ui.forms import record_selectbox, to_decimal
from ui.labels import ENTRY_STATUS_BADGES
from ui.records import finish_action
from ui.session import get_session_user

PAGE_KEY = "harvests"
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")


def _render_harvest_form(actor: User) -> None:
    coffees = production_service.list_own_coffees(actor)
    if not coffees:
        st.warning(
            "Nenhum café de fazenda própria ativo. Cadastre a fazenda própria e o café dela em Cadastros.",
            icon=":material/warning:",
        )
        return
    coffee_id = record_selectbox(st, "Café verde", coffees, None, f"{PAGE_KEY}_coffee", lambda coffee: coffee["label"])
    left, right = st.columns(2)
    quantity = left.number_input("Quantidade beneficiada (kg)", min_value=0.0, step=1.0, format="%.3f")
    total_cost = right.number_input(
        "Custo total (R$)", min_value=0.0, step=50.0, format="%.2f",
        help="Mão de obra da colheita, secagem, beneficiamento e transporte até o armazém.",
    )  # fmt: skip
    harvest_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        harvest_date = st.date_input(
            "Data da colheita", value=today(), max_value=today(), format="DD/MM/YYYY",
            help="Só o administrador registra operações com data retroativa.",
        )  # fmt: skip
    suppliers = production_service.list_service_suppliers(actor)
    left, right = st.columns(2)
    supplier_id = record_selectbox(
        left, "Prestador do serviço (opcional)", suppliers, None, f"{PAGE_KEY}_supplier",
        lambda supplier: supplier["name"], placeholder="Nenhum",
    )  # fmt: skip
    due_date = right.date_input(
        "Vencimento do título",
        value=(harvest_date or today()) + timedelta(days=HARVEST_DEFAULT_TERM_DAYS),
        min_value=harvest_date or today(),
        format="DD/MM/YYYY",
    )
    notes = st.text_area("Observação", placeholder="Ex.: talhão 3, secagem em terreiro", height=68)
    quantity_kg, cost = to_decimal(quantity, 3), to_decimal(total_cost)
    if quantity_kg and cost:
        st.markdown(
            f"Entra no estoque a **R$ {format_decimal(harvest_unit_cost(cost, quantity_kg), 4)}/kg** e gera um "
            f"título a pagar de **{format_currency(cost)}** em Custos de colheita e beneficiamento."
        )
    if st.button("Registrar colheita", type="primary", icon=":material/check:"):
        data = HarvestInput(coffee_id, quantity_kg, cost, supplier_id, due_date, notes)
        try:
            result = production_service.register_harvest(actor, data, harvest_date)
        except AppError as error:
            st.error(str(error))
        else:
            remember_effects(f"Colheita {result.number} registrada.", result.effects)
            finish_action(PAGE_KEY, f"Colheita {result.number} registrada.")


def _harvests_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Número": [row["number"] for row in rows],
            "Café": [row["coffee_label"] for row in rows],
            "Data": [row["harvest_date"] for row in rows],
            "Quantidade (kg)": [to_float(row["quantity_kg"]) for row in rows],
            "Custo total (R$)": [to_float(row["total_cost"]) for row in rows],
            "Custo por kg (R$)": [to_float(row["cost_per_kg"]) for row in rows],
            "Prestador": [row["supplier_name"] for row in rows],
            "Vencimento": [row["due_date"] for row in rows],
            "Título": [
                ENTRY_STATUS_BADGES[EntryDisplayStatus(row["entry_status"])][0] if row["entry_status"] else None
                for row in rows
            ],
        }
    )


def render_harvests_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Colheitas")
    st.caption(
        "Café verde beneficiado da fazenda própria. Entra no estoque pelo custo de colheita e gera o título a pagar."
    )
    show_effects()
    period_column, action_column = st.columns([3, 1], vertical_alignment="bottom")
    start, end = period_input(period_column, "Período da colheita", f"{PAGE_KEY}_period", 365)
    if has_permission(actor, Permission.MANAGE_PRODUCTION) and action_column.button(
        "Nova colheita", type="primary", icon=":material/add:", width="stretch"
    ):
        st.dialog("Nova colheita")(_render_harvest_form)(actor)
    try:
        rows = production_service.list_harvests(actor, PeriodFilters(start, end))
    except AppError as error:
        st.error(str(error))
        return
    if not rows:
        st.info("Nenhuma colheita no período.", icon=":material/info:")
        return
    st.dataframe(
        style_numbers(_harvests_table(rows), {"Quantidade (kg)": 3, "Custo total (R$)": 2, "Custo por kg (R$)": 4}),
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={"Data": DATE_COLUMN, "Vencimento": DATE_COLUMN},
    )
