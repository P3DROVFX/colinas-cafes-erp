from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from core.errors import AppError
from domain.catalog import PackagingKind
from domain.settings import SettingType
from services import catalog as catalog_service
from services import settings as settings_service
from ui.feedback import show_flash
from ui.formatting import format_datetime
from ui.records import finish_action
from ui.session import get_session_user

PAGE_KEY = "settings"
SHIPPING_BOX_KEY = "default_shipping_box_id"
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Torra e envase", ("roaster_capacity_kg", "roast_min_kg", "weight_loss_warn_min_pct", "weight_loss_warn_max_pct",
                        "weight_loss_block_min_pct", "weight_loss_block_max_pct", "roast_batch_alert_days",
                        "product_shelf_life_months")),
    ("Vendas", ("default_shipping_box_id", "quote_validity_days", "max_discount_pct", "wholesale_min_order_kg",
                "wholesale_default_term_days", "overdue_tolerance_days")),
    ("Meios de pagamento", ("credit_card_fee_pct", "credit_card_term_days", "debit_card_fee_pct",
                            "debit_card_term_days")),
    ("Financeiro e estoque", ("due_alert_days", "packaging_lead_time_days", "safety_stock_days",
                              "operation_start_date")),
)  # fmt: skip


def _setting_input(container, row: dict[str, Any], boxes: list[dict[str, Any]]) -> str | None:
    key, label = row["key"], row["description"]
    widget_key = f"{PAGE_KEY}_{key}"
    if key == SHIPPING_BOX_KEY:
        names = {str(box["id"]): f"{box['name']} ({box['capacity_g']} g)" for box in boxes}
        options = list(names)
        index = options.index(row["value"]) if row["value"] in options else None
        return container.selectbox(label, options, index=index, format_func=names.get, placeholder="Nenhuma",
                                   key=widget_key)  # fmt: skip
    value_type = SettingType(row["value_type"])
    if value_type is SettingType.DATE:
        return container.date_input(label, value=date.fromisoformat(row["value"]), format="DD/MM/YYYY",
                                    key=widget_key).isoformat()  # fmt: skip
    if value_type is SettingType.INT:
        return str(container.number_input(label, value=int(row["value"]), step=1, key=widget_key))
    return str(container.number_input(label, value=float(row["value"]), step=0.5, format="%.2f", key=widget_key))


def _render_history(actor) -> None:
    history = settings_service.list_settings_history(actor)
    if not history:
        st.caption("Nenhuma alteração registrada.")
        return
    st.dataframe(
        pd.DataFrame(
            {
                "Quando": [format_datetime(row["created_at"]) for row in history],
                "Parâmetro": [row["new_data"]["key"] for row in history],
                "De": [row["old_data"]["value"] for row in history],
                "Para": [row["new_data"]["value"] for row in history],
                "Usuário": [row["user_email"] for row in history],
            }
        ),
        hide_index=True,
        width="stretch",
        placeholder="—",
    )


def render_settings_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Parâmetros")
    st.caption("Valores usados pelas regras de torra, vendas, pagamentos e alertas. Toda alteração fica registrada.")
    try:
        rows = {row["key"]: row for row in settings_service.list_settings(actor)}
        boxes = [row for row in catalog_service.list_packaging_items(actor) if row["kind"] == PackagingKind.SHIPPING_BOX
                 and row["is_active"]]  # fmt: skip
    except AppError as error:
        st.error(str(error))
        return
    with st.form(f"{PAGE_KEY}_form", border=False):
        values: dict[str, str | None] = {}
        for title, keys in GROUPS:
            with st.container(border=True):
                st.subheader(title)
                columns = st.columns(2)
                for index, key in enumerate(key for key in keys if key in rows):
                    values[key] = _setting_input(columns[index % 2], rows[key], boxes)
        submitted = st.form_submit_button("Salvar parâmetros", type="primary", icon=":material/save:")
    if submitted:
        try:
            changed = settings_service.update_settings(actor, values)
        except AppError as error:
            st.error(str(error))
        else:
            finish_action(PAGE_KEY, f"{len(changed)} parâmetro(s) alterado(s)." if changed else "Nada mudou.")
    st.subheader("Histórico de alterações")
    _render_history(actor)
