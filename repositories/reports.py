from datetime import date
from typing import Any

from psycopg import Connection

INVOICED_STATUSES = "('CONFIRMED', 'SHIPPED', 'DELIVERED')"


def monthly_income_statement(connection: Connection, start_date: date, end_date: date) -> list[dict[str, Any]]:
    """Accrual figures per month: sales by sale date, entries by accrual date, stock adjustments by movement date."""
    return connection.execute(
        f"""
        WITH months AS (
            SELECT generate_series(date_trunc('month', %(start)s::date), date_trunc('month', %(end)s::date),
                                   interval '1 month')::date AS month
        ),
        sales_by_month AS (
            SELECT date_trunc('month', sale_date)::date AS month,
                   SUM(products_amount - discount_amount) AS net_revenue, SUM(freight_amount) AS freight_revenue,
                   SUM(products_cost) AS cost_of_goods, SUM(boxes_cost) AS boxes_cost, count(*) AS sale_count
            FROM sales
            WHERE status IN {INVOICED_STATUSES} AND sale_date BETWEEN %(start)s AND %(end)s
            GROUP BY 1
        ),
        entries_by_month AS (
            SELECT date_trunc('month', e.accrual_date)::date AS month,
                   SUM(e.amount) FILTER (WHERE c.dre_group = 'OTHER_REVENUE') AS other_revenue,
                   SUM(e.amount) FILTER (WHERE c.dre_group = 'SELLING_COST') AS selling_costs,
                   SUM(e.amount) FILTER (WHERE c.dre_group = 'OPERATING_EXPENSE') AS operating_expenses
            FROM financial_entries e JOIN financial_categories c ON c.id = e.category_id
            WHERE e.status <> 'CANCELLED' AND e.accrual_date BETWEEN %(start)s AND %(end)s
            GROUP BY 1
        ),
        adjustments_by_month AS (
            SELECT date_trunc('month', movement_date)::date AS month, SUM(total_value) AS stock_adjustments
            FROM stock_movements
            WHERE movement_type = 'INVENTORY_ADJUSTMENT' AND reason <> 'OPENING'
              AND movement_date BETWEEN %(start)s AND %(end)s
            GROUP BY 1
        )
        SELECT m.month,
               COALESCE(s.net_revenue, 0) AS net_revenue, COALESCE(s.freight_revenue, 0) AS freight_revenue,
               COALESCE(e.other_revenue, 0) AS other_revenue, COALESCE(s.cost_of_goods, 0) AS cost_of_goods,
               COALESCE(e.selling_costs, 0) + COALESCE(s.boxes_cost, 0) AS selling_costs,
               COALESCE(a.stock_adjustments, 0) AS stock_adjustments,
               COALESCE(e.operating_expenses, 0) AS operating_expenses, COALESCE(s.sale_count, 0) AS sale_count
        FROM months m
        LEFT JOIN sales_by_month s ON s.month = m.month
        LEFT JOIN entries_by_month e ON e.month = m.month
        LEFT JOIN adjustments_by_month a ON a.month = m.month
        ORDER BY m.month
        """,
        {"start": start_date, "end": end_date},
    ).fetchall()


def invoiced_sales_summary(connection: Connection, today: date) -> dict[str, Any]:
    return connection.execute(
        f"""
        SELECT COALESCE(SUM(total_amount) FILTER (WHERE sale_date = %(today)s), 0) AS today_amount,
               count(*) FILTER (WHERE sale_date = %(today)s) AS today_count,
               COALESCE(SUM(total_amount), 0) AS month_amount, count(*) AS month_count
        FROM sales
        WHERE status IN {INVOICED_STATUSES} AND sale_date BETWEEN date_trunc('month', %(today)s::date) AND %(today)s
        """,
        {"today": today},
    ).fetchone()
