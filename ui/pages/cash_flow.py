from datetime import date

import pandas as pd
import streamlit as st

from core.errors import AppError
from domain.finance import Granularity, balance_series
from services import finance as finance_service
from services.finance import CashFlowReport, CashFlowRequest
from ui.filters import period_input
from ui.formatting import format_currency, format_signed_currency, style_numbers, to_float
from ui.forms import enum_selectbox
from ui.labels import GRANULARITY_LABELS
from ui.session import get_session_user

PAGE_KEY = "cash_flow"
PERIOD_FORMATS = {Granularity.DAY: "%d/%m/%Y", Granularity.WEEK: "sem. %d/%m", Granularity.MONTH: "%m/%Y"}


def _render_realized(report: CashFlowReport, granularity: Granularity, start_date: date, end_date: date) -> None:
    columns = st.columns(4)
    columns[0].metric("Saldo inicial", format_currency(report.opening_balance))
    columns[1].metric("Entradas", format_currency(report.inflow))
    columns[2].metric("Saídas", format_currency(report.outflow))
    columns[3].metric(
        "Saldo final", format_currency(report.closing_balance),
        delta=format_signed_currency(report.closing_balance - report.opening_balance),
    )  # fmt: skip
    if not report.periods:
        st.info("Nenhuma liquidação no período.", icon=":material/info:")
        return
    labels = [period.start.strftime(PERIOD_FORMATS[granularity]) for period in report.periods]
    series = balance_series(report.periods, report.opening_balance, start_date, end_date, granularity)
    st.line_chart(
        pd.DataFrame({"Data": pd.to_datetime([day for day, _ in series]),
                      "Saldo (R$)": [to_float(balance) for _, balance in series]}),
        x="Data", y="Saldo (R$)", x_label="",
    )  # fmt: skip
    frame = pd.DataFrame(
        {
            "Período": labels,
            "Entradas (R$)": [to_float(period.inflow) for period in report.periods],
            "Saídas (R$)": [to_float(period.outflow) for period in report.periods],
            "Resultado (R$)": [to_float(period.net) for period in report.periods],
            "Saldo acumulado (R$)": [to_float(period.balance) for period in report.periods],
        }
    )
    money = {column: 2 for column in frame.columns if column != "Período"}
    st.dataframe(style_numbers(frame, money), hide_index=True, width="stretch")


def _render_forecast(report: CashFlowReport) -> None:
    st.subheader("Previsto")
    st.caption("Títulos pendentes por vencimento, a partir do saldo atual das contas escolhidas. Vencidos entram já.")
    frame = pd.DataFrame(
        {
            "Horizonte": [f"Próximos {bucket.horizon_days} dias" for bucket in report.forecast],
            "A receber (R$)": [to_float(bucket.inflow) for bucket in report.forecast],
            "A pagar (R$)": [to_float(bucket.outflow) for bucket in report.forecast],
            "Saldo projetado (R$)": [to_float(bucket.projected_balance) for bucket in report.forecast],
        }
    )
    money = {column: 2 for column in frame.columns if column != "Horizonte"}
    st.dataframe(style_numbers(frame, money), hide_index=True, width="stretch")


def render_cash_flow_page() -> None:
    actor = get_session_user()
    st.title("Fluxo de caixa")
    st.caption(
        "Regime de caixa: tudo o que entrou e saiu pelas contas, pela data da liquidação, inclusive as compras de "
        "estoque. O resultado do negócio fica na DRE."
    )
    try:
        accounts = finance_service.list_account_balances(actor)
    except AppError as error:
        st.error(str(error))
        return
    names = {row["id"]: row["name"] for row in accounts}
    period_column, account_column, granularity_column = st.columns([1.4, 2, 1], vertical_alignment="bottom")
    start, end = period_input(period_column, "Período", f"{PAGE_KEY}_period", 30)
    account_ids = account_column.multiselect(
        "Contas", list(names), default=list(names), format_func=names.get, key=f"{PAGE_KEY}_accounts"
    )
    granularity = enum_selectbox(granularity_column, "Agrupar por", GRANULARITY_LABELS, Granularity.DAY,
                                 f"{PAGE_KEY}_granularity")  # fmt: skip
    try:
        report = finance_service.get_cash_flow(actor, CashFlowRequest(start, end, tuple(account_ids), granularity))
    except AppError as error:
        st.error(str(error))
        return
    st.subheader("Realizado")
    _render_realized(report, granularity, start, end)
    _render_forecast(report)
