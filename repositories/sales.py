from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection, sql

SALE_COLUMNS = """
    s.id, s.number, s.customer_id, s.channel, s.delivery_type, s.payment_method, s.status, s.quote_date,
    s.quote_valid_until, s.sale_date, s.products_amount, s.discount_amount, s.freight_amount, s.total_amount,
    s.total_weight_g, s.box_count, s.products_cost, s.boxes_cost, s.payment_fee, s.actual_freight_cost,
    s.delivery_address, s.carrier, s.tracking_code, s.notes, s.user_email, s.created_at, s.confirmed_at,
    s.shipped_at, s.delivered_at, s.cancelled_at, s.cancel_reason,
    c.name AS customer_name, c.document AS customer_document, c.person_type AS customer_person_type,
    CASE WHEN s.status = 'QUOTE' AND s.quote_valid_until < %(today)s THEN 'EXPIRED' ELSE s.status END
      AS display_status
"""

PRODUCT_COLUMNS = """
    id, sku, sku || ' · ' || name AS label, name, weight_g, price_local, price_online, price_wholesale, stock,
    avg_unit_cost, is_active
"""

STATUS_TIMESTAMPS = {
    "CONFIRMED": "confirmed_at",
    "SHIPPED": "shipped_at",
    "DELIVERED": "delivered_at",
    "CANCELLED": "cancelled_at",
}


def next_sale_number(connection: Connection, year: int) -> str:
    sequence = connection.execute("SELECT nextval('sale_number_seq') AS value").fetchone()["value"]
    return f"V-{year}-{sequence:06d}"


def insert_sale(connection: Connection, values: dict[str, Any]) -> int:
    query = sql.SQL("INSERT INTO sales ({}) VALUES ({}) RETURNING id").format(
        sql.SQL(", ").join(map(sql.Identifier, values)), sql.SQL(", ").join(sql.Placeholder() * len(values))
    )
    return connection.execute(query, list(values.values())).fetchone()["id"]


def update_sale(connection: Connection, sale_id: int, values: dict[str, Any]) -> None:
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder()) for column in values
    )
    connection.execute(sql.SQL("UPDATE sales SET {} WHERE id = %s").format(assignments), [*values.values(), sale_id])


def set_status(connection: Connection, sale_id: int, status: str, values: dict[str, Any] | None = None) -> None:
    timestamp = STATUS_TIMESTAMPS[status]
    update_sale(connection, sale_id, {**(values or {}), "status": status})
    query = sql.SQL("UPDATE sales SET {} = now() WHERE id = %s").format(sql.Identifier(timestamp))
    connection.execute(query, (sale_id,))


def insert_sale_item(connection: Connection, sale_id: int, product_id: int, quantity: int, price: Decimal) -> None:
    connection.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
        (sale_id, product_id, quantity, price),
    )


def delete_sale_items(connection: Connection, sale_id: int) -> None:
    connection.execute("DELETE FROM sale_items WHERE sale_id = %s", (sale_id,))


def set_item_cost_snapshot(connection: Connection, item_id: int, unit_cost: Decimal) -> None:
    connection.execute("UPDATE sale_items SET unit_cost_snapshot = %s WHERE id = %s", (unit_cost, item_id))


def find_sale(connection: Connection, sale_id: int, today: date, for_update: bool = False) -> dict[str, Any] | None:
    lock = "FOR UPDATE OF s" if for_update else ""
    return connection.execute(
        f"SELECT {SALE_COLUMNS} FROM sales s JOIN customers c ON c.id = s.customer_id WHERE s.id = %(id)s {lock}",
        {"id": sale_id, "today": today},
    ).fetchone()


def list_sale_items(connection: Connection, sale_id: int) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT i.id, i.product_id, i.quantity, i.unit_price, i.unit_cost_snapshot, i.quantity * i.unit_price AS amount,
               p.sku, p.sku || ' · ' || p.name AS label, p.weight_g
        FROM sale_items i JOIN products p ON p.id = i.product_id
        WHERE i.sale_id = %s
        ORDER BY i.product_id
        """,
        (sale_id,),
    ).fetchall()


def list_sales(
    connection: Connection,
    start_date: date,
    end_date: date,
    channels: list[str],
    display_statuses: list[str],
    customer_id: int | None,
    today: date,
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT * FROM (
            SELECT {SALE_COLUMNS}
            FROM sales s JOIN customers c ON c.id = s.customer_id
            WHERE COALESCE(s.sale_date, s.quote_date) BETWEEN %(start)s AND %(end)s
              AND s.channel = ANY(%(channels)s)
              AND (%(customer)s::bigint IS NULL OR s.customer_id = %(customer)s)
        ) sales
        WHERE display_status = ANY(%(statuses)s)
        ORDER BY COALESCE(sale_date, quote_date) DESC, id DESC
        """,
        {
            "start": start_date,
            "end": end_date,
            "channels": channels,
            "statuses": display_statuses,
            "customer": customer_id,
            "today": today,
        },
    ).fetchall()


def list_customer_options(connection: Connection, include_id: int | None = None) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, person_type, segment, address, city, state, payment_term_days, credit_limit, is_system,
               is_active
        FROM customers
        WHERE is_active OR id = %s
        ORDER BY is_system DESC, name
        """,
        (include_id,),
    ).fetchall()


def find_customer(connection: Connection, customer_id: int) -> dict[str, Any] | None:
    return connection.execute(
        """
        SELECT id, name, person_type, segment, address, city, state, payment_term_days, credit_limit, is_system,
               is_active
        FROM customers WHERE id = %s
        """,
        (customer_id,),
    ).fetchone()


def list_sale_products(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(f"SELECT {PRODUCT_COLUMNS} FROM products WHERE is_active ORDER BY sku").fetchall()


def find_sale_products(connection: Connection, product_ids: list[int]) -> list[dict[str, Any]]:
    return connection.execute(f"SELECT {PRODUCT_COLUMNS} FROM products WHERE id = ANY(%s)", (product_ids,)).fetchall()


def find_shipping_box(connection: Connection, preferred_id: int | None) -> dict[str, Any] | None:
    return connection.execute(
        """
        SELECT id, name, capacity_g FROM packaging_items
        WHERE kind = 'SHIPPING_BOX' AND is_active
        ORDER BY id = %s DESC, id
        LIMIT 1
        """,
        (preferred_id,),
    ).fetchone()


def customer_credit_position(connection: Connection, customer_id: int, today: date) -> dict[str, Any]:
    return connection.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS open_amount,
               COALESCE(MAX(GREATEST(%(today)s - due_date, 0)), 0) AS max_overdue_days
        FROM financial_entries
        WHERE customer_id = %(customer)s AND entry_type = 'RECEIVABLE' AND status = 'PENDING'
        """,
        {"customer": customer_id, "today": today},
    ).fetchone()


def customer_history(connection: Connection, customer_id: int) -> dict[str, Any]:
    return connection.execute(
        """
        SELECT count(*) AS order_count, COALESCE(SUM(total_amount), 0) AS total_spent, MAX(sale_date) AS last_sale_date
        FROM sales
        WHERE customer_id = %s AND status IN ('CONFIRMED', 'SHIPPED', 'DELIVERED')
        """,
        (customer_id,),
    ).fetchone()


def insert_event(
    connection: Connection, sale_id: int, from_status: str | None, to_status: str, notes: str | None, user_email: str
) -> None:
    connection.execute(
        "INSERT INTO sale_events (sale_id, from_status, to_status, notes, user_email) VALUES (%s, %s, %s, %s, %s)",
        (sale_id, from_status, to_status, notes, user_email),
    )


def list_events(connection: Connection, sale_id: int) -> list[dict[str, Any]]:
    return connection.execute(
        "SELECT from_status, to_status, notes, user_email, created_at FROM sale_events WHERE sale_id = %s ORDER BY id",
        (sale_id,),
    ).fetchall()
