import streamlit as st

from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.inventory import StockItemKind, StockStatus, stock_status
from services import inventory as inventory_service
from services import production as production_service
from services.system import get_system_status
from ui.formatting import format_datetime
from ui.labels import ROLE_LABELS
from ui.session import get_session_user

MINIMUM_STOCK_KINDS = (StockItemKind.GREEN_COFFEE, StockItemKind.PACKAGING_ITEM, StockItemKind.PRODUCT)


def _items_below_minimum(actor: User) -> list[str]:
    return [
        row["label"]
        for kind in MINIMUM_STOCK_KINDS
        for row in inventory_service.list_stock_positions(actor, kind)
        if row["is_active"] and row["min_stock"] and stock_status(row["stock"], row["min_stock"]) is not StockStatus.OK
    ]


def _render_alerts(actor: User) -> None:
    alerts = []
    below_minimum = _items_below_minimum(actor)
    if below_minimum:
        alerts.append((f"Abaixo do estoque mínimo: {', '.join(below_minimum)}.", ":material/inventory_2:"))
    if has_permission(actor, Permission.VIEW_PRODUCTION):
        alert_days, stale = production_service.list_stale_roast_batches(actor)
        if stale:
            codes = ", ".join(f"{row['code']} ({row['days_since_roast']} dias)" for row in stale)
            alerts.append((f"Lotes torrados há mais de {alert_days} dias sem envase: {codes}.", ":material/schedule:"))
    st.subheader("Alertas")
    if not alerts:
        st.success("Nenhum alerta de estoque ou de frescor.", icon=":material/check_circle:")
    for message, icon in alerts:
        st.warning(message, icon=icon)


def render_home_page() -> None:
    user = get_session_user()
    first_name = user.name.split()[0]
    st.title(f"Olá, {first_name}!")
    st.write("Bem-vindo ao sistema de gestão da **Colinas Cafés**.")

    status = get_system_status()
    columns = st.columns(3)
    columns[0].metric("Seu perfil", ROLE_LABELS[user.role])
    columns[1].metric("Versão do banco", status.schema_version or "—")
    columns[2].metric("Horário do servidor", format_datetime(status.database_time))
    try:
        _render_alerts(user)
    except AppError as error:
        st.error(str(error))
