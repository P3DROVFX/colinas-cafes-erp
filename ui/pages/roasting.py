from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.catalog import RoastProfile
from domain.inventory import AdjustmentReason, MovementType
from domain.numbers import format_decimal
from domain.production import (
    RoastBatchStatus,
    RoastInput,
    RoastLimits,
    is_unusual_weight_loss,
    roasted_cost_per_kg,
    weight_loss_pct,
)
from services import production as production_service
from services.production import PeriodFilters, RoastBatchDetail
from ui.effects import remember_effects, show_effects
from ui.feedback import show_flash
from ui.filters import period_input
from ui.formatting import style_numbers, to_float
from ui.forms import enum_selectbox, record_selectbox, to_decimal
from ui.labels import ADJUSTMENT_REASON_LABELS, MOVEMENT_TYPE_LABELS, ROAST_BATCH_STATUS_BADGES, ROAST_PROFILE_LABELS
from ui.records import finish_action
from ui.session import get_session_user

PAGE_KEY = "roasting"
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")


def _kg(value: Decimal) -> str:
    return f"{format_decimal(value, 3)} kg"


def _per_kg(value: Decimal) -> str:
    return f"R$ {format_decimal(value, 4)}/kg"


def _percent(value: Decimal) -> str:
    return f"{format_decimal(value, 2)}%"


def _render_roast_preview(green: Decimal, roasted: Decimal, green_cost: Decimal, limits: RoastLimits) -> bool:
    """Shows the weight loss and roasted cost before saving and returns whether the loss needs confirmation."""
    if not green or not roasted or not 0 < roasted < green:
        return False
    loss = weight_loss_pct(green, roasted)
    loss_column, cost_column = st.columns(2)
    loss_column.metric("Quebra", _percent(loss))
    cost_column.metric("Custo do kg torrado", _per_kg(roasted_cost_per_kg(green, green_cost, roasted)))
    if not limits.block_min_pct <= loss <= limits.block_max_pct:
        st.error(
            f"Quebra fora do possível ({_percent(limits.block_min_pct)} a {_percent(limits.block_max_pct)}). "
            "Confira os pesos digitados.",
            icon=":material/block:",
        )
        return False
    if is_unusual_weight_loss(loss, limits):
        st.warning(
            f"Quebra fora da faixa usual ({_percent(limits.warn_min_pct)} a {_percent(limits.warn_max_pct)}).",
            icon=":material/warning:",
        )
        return True
    return False


def _render_roast_form(actor: User) -> None:
    coffees = production_service.list_roastable_coffees(actor)
    if not coffees:
        st.warning(
            "Nenhum café verde com saldo. Receba uma compra ou registre uma colheita.", icon=":material/warning:"
        )
        return
    limits = production_service.get_roast_limits(actor)
    coffees_by_id = {coffee["id"]: coffee for coffee in coffees}
    coffee_id = record_selectbox(
        st, "Café verde", coffees, None, f"{PAGE_KEY}_coffee",
        lambda coffee: f"{coffee['label']} · {_kg(coffee['stock_kg'])} em estoque",
    )  # fmt: skip
    profile = enum_selectbox(st, "Perfil de torra", ROAST_PROFILE_LABELS, RoastProfile.MEDIUM, f"{PAGE_KEY}_profile")
    left, right = st.columns(2)
    green = left.number_input(
        "Peso verde (kg)", min_value=0.0, max_value=float(limits.capacity_kg), step=0.5, format="%.3f",
        help=f"Capacidade do torrador: {format_decimal(limits.capacity_kg, 0)} kg por batelada.",
    )  # fmt: skip
    roasted = right.number_input("Peso torrado (kg)", min_value=0.0, step=0.1, format="%.3f")
    green_kg, roasted_kg = to_decimal(green, 3), to_decimal(roasted, 3)
    green_cost = coffees_by_id[coffee_id]["avg_cost_per_kg"] if coffee_id else Decimal("0")
    needs_confirmation = _render_roast_preview(green_kg, roasted_kg, green_cost, limits)
    confirmed = needs_confirmation and st.checkbox("Confirmo que os pesos estão corretos")
    with st.expander("Dados da torra (opcional)"):
        left, middle, right = st.columns(3)
        roast_time = left.number_input("Tempo (min)", min_value=0.0, step=0.5, format="%.1f", value=None)
        temperature = middle.number_input("Temperatura final (°C)", min_value=0.0, step=1.0, format="%.1f", value=None)
        location = right.text_input("Local", placeholder="Ex.: Torrefação – Bancada 1")
        notes = st.text_area("Notas sensoriais", placeholder="Ex.: primeiro crack aos 8 min, notas de caramelo")
    roast_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        roast_date = st.date_input("Data da torra", value=today(), max_value=today(), format="DD/MM/YYYY")
    if st.button("Registrar torra", type="primary", icon=":material/local_fire_department:"):
        data = RoastInput(
            coffee_id, profile, green_kg, roasted_kg, confirmed, to_decimal(roast_time, 1),
            to_decimal(temperature, 1), location, notes,
        )  # fmt: skip
        try:
            result = production_service.roast(actor, data, roast_date)
        except AppError as error:
            st.error(str(error))
        else:
            details = [f"Quebra **{_percent(result.weight_loss_pct)}** · custo **{_per_kg(result.cost_per_kg)}**"]
            remember_effects(f"Lote {result.code} torrado.", result.effects, details)
            finish_action(PAGE_KEY, f"Lote {result.code} registrado.")


def _render_close_dialog(actor: User, batch: dict[str, Any]) -> None:
    st.markdown(
        f"Encerrar o lote **{batch['code']}**? A sobra de {_kg(batch['stock_kg'])} sai do estoque como perda "
        "e o lote deixa de aparecer no envase."
    )
    notes = st.text_input("Observação", placeholder="Ex.: sobra menor que um pacote")
    if st.button("Encerrar lote", type="primary", icon=":material/inventory:"):
        try:
            effects = production_service.close_roast_batch(actor, batch["id"], notes)
        except AppError as error:
            st.error(str(error))
        else:
            remember_effects(f"Lote {batch['code']} encerrado.", effects)
            finish_action(PAGE_KEY, f"Lote {batch['code']} encerrado.")


def _batches_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Lote": [row["code"] for row in rows],
            "Café": [row["coffee_code"] for row in rows],
            "Perfil": [ROAST_PROFILE_LABELS[RoastProfile(row["roast_profile"])] for row in rows],
            "Torra": [row["roast_date"] for row in rows],
            "Verde (kg)": [to_float(row["green_weight_kg"]) for row in rows],
            "Torrado (kg)": [to_float(row["roasted_weight_kg"]) for row in rows],
            "Quebra (%)": [to_float(row["weight_loss_pct"]) for row in rows],
            "Custo por kg (R$)": [to_float(row["cost_per_kg"]) for row in rows],
            "Saldo (kg)": [to_float(row["stock_kg"]) for row in rows],
            "Dias desde a torra": [
                row["days_since_roast"] if row["status"] == RoastBatchStatus.OPEN else None for row in rows
            ],
            "Situação": [ROAST_BATCH_STATUS_BADGES[RoastBatchStatus(row["status"])][0] for row in rows],
        }
    )


def _render_packings(detail: RoastBatchDetail) -> None:
    if not detail.packings:
        st.caption("Este lote ainda não foi envasado.")
        return
    frame = pd.DataFrame(
        {
            "Envase": [row["code"] for row in detail.packings],
            "Produto": [row["product_sku"] for row in detail.packings],
            "Data": [row["packing_date"] for row in detail.packings],
            "Pacotes": [row["bag_count"] for row in detail.packings],
            "Consumo (kg)": [to_float(row["consumed_kg"]) for row in detail.packings],
            "Custo do pacote (R$)": [to_float(row["unit_cost"]) for row in detail.packings],
        }
    )
    st.dataframe(
        style_numbers(frame, {"Consumo (kg)": 3, "Custo do pacote (R$)": 4}),
        hide_index=True,
        width="stretch",
        column_config={"Data": DATE_COLUMN},
    )


def _render_movements(detail: RoastBatchDetail) -> None:
    frame = pd.DataFrame(
        {
            "Data": [row["movement_date"] for row in detail.movements],
            "Tipo": [MOVEMENT_TYPE_LABELS[MovementType(row["movement_type"])] for row in detail.movements],
            "Quantidade (kg)": [to_float(row["quantity"]) for row in detail.movements],
            "Saldo após (kg)": [to_float(row["balance_after"]) for row in detail.movements],
            "Motivo": [
                ADJUSTMENT_REASON_LABELS[AdjustmentReason(row["reason"])] if row["reason"] else None
                for row in detail.movements
            ],
            "Observação": [row["notes"] for row in detail.movements],
        }
    )
    st.dataframe(
        style_numbers(frame, {"Quantidade (kg)": 3, "Saldo após (kg)": 3}),
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={"Data": DATE_COLUMN},
    )


def _render_detail(actor: User, batch_id: int) -> None:
    try:
        detail = production_service.get_roast_batch_detail(actor, batch_id)
    except AppError as error:
        st.error(str(error))
        return
    batch = detail.batch
    status = RoastBatchStatus(batch["status"])
    with st.container(border=True):
        title_column, badge_column = st.columns([4, 1], vertical_alignment="center")
        title_column.subheader(batch["code"])
        label, color, icon = ROAST_BATCH_STATUS_BADGES[status]
        with badge_column:
            st.badge(label, color=color, icon=icon)
        st.markdown(
            f"{batch['coffee_label']} · torra {ROAST_PROFILE_LABELS[RoastProfile(batch['roast_profile'])].lower()} "
            f"em {batch['roast_date']:%d/%m/%Y} por {batch['user_email']}"
        )
        columns = st.columns(4)
        columns[0].metric("Torrado", _kg(batch["roasted_weight_kg"]), help=f"De {_kg(batch['green_weight_kg'])} verde")
        columns[1].metric("Quebra", _percent(batch["weight_loss_pct"]))
        columns[2].metric("Custo por kg", f"R$ {format_decimal(batch['cost_per_kg'], 4)}")
        columns[3].metric("Saldo", _kg(batch["stock_kg"]))
        extras = [
            f"Tempo {format_decimal(batch['roast_time_min'], 1)} min" if batch["roast_time_min"] else None,
            f"Temperatura final {format_decimal(batch['end_temperature_c'], 1)} °C"
            if batch["end_temperature_c"]
            else None,
            f"Local: {batch['location']}" if batch["location"] else None,
        ]
        if extras := [extra for extra in extras if extra]:
            st.caption(" · ".join(extras))
        if batch["notes"]:
            st.caption(f"Notas: {batch['notes']}")
        can_close = status is RoastBatchStatus.OPEN and has_permission(actor, Permission.MANAGE_PRODUCTION)
        if can_close and st.button("Encerrar lote", icon=":material/inventory:"):
            st.dialog("Encerrar lote torrado")(_render_close_dialog)(actor, batch)
        packings_tab, movements_tab = st.tabs(["Envases", "Movimentos de estoque"])
        with packings_tab:
            _render_packings(detail)
        with movements_tab:
            _render_movements(detail)


def _render_freshness_alert(actor: User) -> None:
    alert_days, stale = production_service.list_stale_roast_batches(actor)
    if not stale:
        return
    codes = ", ".join(f"{row['code']} ({row['days_since_roast']} dias)" for row in stale)
    st.warning(
        f"Lotes torrados há mais de {alert_days} dias sem envase: {codes}. Envase-os primeiro ou encerre a sobra.",
        icon=":material/schedule:",
    )


def render_roasting_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Torras")
    st.caption(
        "Cada torra baixa o café verde e cria um lote torrado com quebra e custo por kg. Torras não se estornam."
    )
    show_effects()
    try:
        _render_freshness_alert(actor)
    except AppError as error:
        st.error(str(error))
    period_column, status_column, action_column = st.columns([1.6, 1.6, 1], vertical_alignment="bottom")
    start, end = period_input(period_column, "Período da torra", f"{PAGE_KEY}_period", 90)
    statuses = status_column.multiselect(
        "Situação",
        list(RoastBatchStatus),
        default=[RoastBatchStatus.OPEN],
        format_func=lambda status: ROAST_BATCH_STATUS_BADGES[status][0],
        key=f"{PAGE_KEY}_statuses",
    )
    if has_permission(actor, Permission.MANAGE_PRODUCTION) and action_column.button(
        "Nova torra", type="primary", icon=":material/add:", width="stretch"
    ):
        st.dialog("Nova torra", width="large")(_render_roast_form)(actor)
    try:
        rows = production_service.list_roast_batches(
            actor, PeriodFilters(start, end), tuple(statuses or RoastBatchStatus)
        )
    except AppError as error:
        st.error(str(error))
        return
    if not rows:
        st.info("Nenhum lote torrado no período e nas situações escolhidas.", icon=":material/info:")
        return
    version = st.session_state.get(f"{PAGE_KEY}_table_version", 0)
    event = st.dataframe(
        style_numbers(
            _batches_table(rows),
            {"Verde (kg)": 3, "Torrado (kg)": 3, "Quebra (%)": 2, "Custo por kg (R$)": 4, "Saldo (kg)": 3},
        ),
        hide_index=True,
        width="stretch",
        placeholder="—",
        on_select="rerun",
        selection_mode="single-row",
        column_config={"Torra": DATE_COLUMN},
        key=f"{PAGE_KEY}_table_{version}",
    )
    selected = event.selection.rows
    if selected and selected[0] < len(rows):
        _render_detail(actor, rows[selected[0]]["id"])
    else:
        st.caption("Selecione um lote para ver os envases, os movimentos e as ações.")
