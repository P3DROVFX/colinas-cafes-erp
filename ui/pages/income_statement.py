import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.dates import add_months
from domain.finance import IncomeStatement, sum_statements
from domain.numbers import format_decimal
from services import finance as finance_service
from ui.formatting import format_currency, style_numbers, to_float
from ui.session import get_session_user

PAGE_KEY = "income_statement"
LINES: tuple[tuple[str, str, int], ...] = (
    ("Receita líquida de vendas", "net_revenue", 1),
    ("Frete cobrado", "freight_revenue", 1),
    ("Outras receitas", "other_revenue", 1),
    ("= Receita total", "total_revenue", 1),
    ("(−) Custo dos produtos vendidos (CMV)", "cost_of_goods", -1),
    ("= Lucro bruto", "gross_profit", 1),
    ("(−) Custos de venda (taxas, fretes e caixas)", "selling_costs", -1),
    ("(±) Ajustes e perdas de estoque", "stock_adjustments", 1),
    ("(−) Despesas operacionais", "operating_expenses", -1),
    ("= Resultado do período", "result", 1),
)


def _line_value(item: IncomeStatement, field: str, sign: int) -> float:
    return to_float(getattr(item, field) * sign) + 0.0


def _statement_table(statements: list[IncomeStatement], total: IncomeStatement) -> pd.DataFrame:
    columns = {f"{item.month:%m/%Y}": item for item in statements} | {"Total": total}
    return pd.DataFrame(
        {month: [_line_value(item, field, sign) for _, field, sign in LINES] for month, item in columns.items()},
        index=[label for label, _, _ in LINES],
    )


def render_income_statement_page() -> None:
    actor = get_session_user()
    st.title("Resultado (DRE gerencial)")
    st.caption(
        "Regime de competência: vendas pela data da venda, menos o CMV registrado em cada venda, os custos de venda e "
        "as despesas pela data de competência. Compras de café e embalagens viram estoque e só entram como CMV."
    )
    start, end = st.columns(2)
    start_month = start.date_input(
        "De", value=add_months(today().replace(day=1), -5), format="DD/MM/YYYY", key=f"{PAGE_KEY}_start"
    )
    end_month = end.date_input("Até", value=today(), format="DD/MM/YYYY", key=f"{PAGE_KEY}_end")
    try:
        statements = finance_service.get_income_statement(actor, start_month, end_month)
    except AppError as error:
        st.error(str(error))
        return
    total = sum_statements(start_month, statements)
    columns = st.columns(4)
    columns[0].metric("Receita total", format_currency(total.total_revenue))
    columns[1].metric("Lucro bruto", format_currency(total.gross_profit))
    margin = total.gross_margin_pct
    columns[2].metric("Margem bruta", f"{format_decimal(margin, 1)}%" if margin is not None else "—")
    columns[3].metric("Resultado", format_currency(total.result))
    frame = _statement_table(statements, total)
    st.dataframe(style_numbers(frame, {column: 2 for column in frame.columns}), width="stretch")
    st.caption("Valores em R$. Custos e despesas aparecem negativos; ajustes de estoque podem somar ou subtrair.")
