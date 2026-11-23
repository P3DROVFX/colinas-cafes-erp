import streamlit as st

from core.errors import AppError
from services import dashboard as dashboard_service
from services.dashboard import HomeSummary
from ui.formatting import format_currency
from ui.labels import ROLE_LABELS
from ui.session import available_pages, get_session_user

SHORTCUTS = ("vendas", "torras", "envases", "compras", "contas", "fluxo-de-caixa", "estoque", "extrato")
MAX_SHORTCUTS = 4
MAX_ALERT_ITEMS = 5


def _render_cards(summary: HomeSummary) -> None:
    cards = []
    if summary.sales is not None:
        sales = summary.sales
        cards.append(("Vendas de hoje", format_currency(sales["today_amount"]), f"{sales['today_count']} venda(s)"))
        cards.append(("Vendas do mês", format_currency(sales["month_amount"]), f"{sales['month_count']} venda(s)"))
    for label, entries in (("A receber vencido", summary.receivables), ("A pagar vencido", summary.payables)):
        if entries is not None:
            due_soon = f"Vence em {summary.due_alert_days} dias: {format_currency(entries.due_soon_amount)}"
            cards.append((label, format_currency(entries.overdue_amount), due_soon))
    if not cards:
        return
    for column, (label, value, caption) in zip(st.columns(len(cards)), cards, strict=True):
        with column.container(border=True):
            st.metric(label, value)
            st.caption(caption)


def _summarize(items: list[str]) -> str:
    if len(items) <= MAX_ALERT_ITEMS:
        return ", ".join(items)
    return f"{', '.join(items[:MAX_ALERT_ITEMS])} e mais {len(items) - MAX_ALERT_ITEMS}"


def _render_alerts(summary: HomeSummary) -> None:
    alerts = []
    if summary.below_minimum:
        alerts.append((f"Abaixo do estoque mínimo: {_summarize(summary.below_minimum)}.", ":material/inventory_2:"))
    if summary.stale_batches:
        codes = _summarize([f"{row['code']} ({row['days_since_roast']} dias)" for row in summary.stale_batches])
        alerts.append(
            (f"Lotes torrados há mais de {summary.freshness_days} dias sem envase: {codes}.", ":material/schedule:")
        )
    overdue = sum(entries.overdue_count for entries in (summary.payables, summary.receivables) if entries)
    if overdue:
        alerts.append((f"{overdue} título(s) vencido(s) em Contas a pagar e a receber.", ":material/event_busy:"))
    st.subheader("Alertas")
    if not alerts:
        st.success("Nenhum alerta de estoque, frescor ou vencimento.", icon=":material/check_circle:")
    for message, icon in alerts:
        st.warning(message, icon=icon)


def _render_shortcuts() -> None:
    pages = available_pages()
    shortcuts = [pages[path] for path in SHORTCUTS if path in pages][:MAX_SHORTCUTS]
    if not shortcuts:
        return
    st.subheader("Atalhos")
    columns = st.columns(len(shortcuts))
    for column, page in zip(columns, shortcuts, strict=True):
        column.page_link(page, label=page.title, icon=page.icon, width="stretch")


def render_home_page() -> None:
    user = get_session_user()
    st.title(f"Olá, {user.name.split()[0]}!")
    st.caption(f"Colinas Cafés · perfil {ROLE_LABELS[user.role]}")
    try:
        summary = dashboard_service.get_home_summary(user)
    except AppError as error:
        st.error(str(error))
        return
    _render_cards(summary)
    _render_alerts(summary)
    _render_shortcuts()
