from datetime import date
from typing import Any

from psycopg import Connection, sql

BATCH_COLUMNS = """
    r.id, r.code, r.green_coffee_id, r.roast_profile, r.roast_date, r.green_weight_kg, r.roasted_weight_kg,
    r.weight_loss_pct, r.green_cost_per_kg, r.cost_per_kg, r.stock_kg, r.status, r.location,
    r.roast_time_min, r.end_temperature_c, r.notes, r.user_email, r.closed_at,
    g.code AS coffee_code, g.code || ' · ' || g.name AS coffee_label
"""


def _insert(connection: Connection, table: str, values: dict[str, Any]) -> int:
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    return connection.execute(query, list(values.values())).fetchone()["id"]


def next_harvest_number(connection: Connection, year: int) -> str:
    sequence = connection.execute("SELECT nextval('harvest_number_seq') AS value").fetchone()["value"]
    return f"COL-{year}-{sequence:06d}"


def next_daily_sequence(connection: Connection, table: str, prefix: str) -> int:
    query = sql.SQL(
        "SELECT COALESCE(MAX(substring(code FROM '[0-9]+$')::int), 0) + 1 AS value FROM {} WHERE code LIKE %s"
    ).format(sql.Identifier(table))
    return connection.execute(query, (f"{prefix}-%",)).fetchone()["value"]


def insert_harvest(connection: Connection, values: dict[str, Any]) -> int:
    return _insert(connection, "harvests", values)


def insert_roast_batch(connection: Connection, values: dict[str, Any]) -> int:
    return _insert(connection, "roast_batches", values)


def insert_packing_batch(connection: Connection, values: dict[str, Any]) -> int:
    return _insert(connection, "packing_batches", values)


def find_coffee_origin(connection: Connection, green_coffee_id: int) -> dict[str, Any] | None:
    return connection.execute(
        """
        SELECT g.is_active, f.is_own FROM green_coffees g JOIN farms f ON f.id = g.farm_id WHERE g.id = %s
        """,
        (green_coffee_id,),
    ).fetchone()


def list_own_coffees(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT g.id, g.code || ' · ' || g.name || ' (' || g.harvest_year || ')' AS label, g.stock_kg, g.avg_cost_per_kg
        FROM green_coffees g JOIN farms f ON f.id = g.farm_id
        WHERE g.is_active AND f.is_own
        ORDER BY label
        """
    ).fetchall()


def list_roastable_coffees(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, code || ' · ' || name AS label, stock_kg, avg_cost_per_kg
        FROM green_coffees
        WHERE is_active AND stock_kg > 0
        ORDER BY label
        """
    ).fetchall()


def list_harvests(connection: Connection, start_date: date, end_date: date, today: date) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT h.id, h.number, h.harvest_date, h.quantity_kg, h.total_cost, h.cost_per_kg, h.due_date, h.notes,
               h.user_email, g.code || ' · ' || g.name AS coffee_label, s.name AS supplier_name,
               CASE WHEN e.status = 'PENDING' AND e.due_date < %(today)s THEN 'OVERDUE' ELSE e.status END
                 AS entry_status
        FROM harvests h
        JOIN green_coffees g ON g.id = h.green_coffee_id
        LEFT JOIN suppliers s ON s.id = h.service_supplier_id
        LEFT JOIN financial_entries e ON e.source_module = 'PRODUCTION' AND e.source_id = h.id
        WHERE h.harvest_date BETWEEN %(start)s AND %(end)s
        ORDER BY h.harvest_date DESC, h.id DESC
        """,
        {"start": start_date, "end": end_date, "today": today},
    ).fetchall()


def find_roast_batch(connection: Connection, roast_batch_id: int, for_update: bool = False) -> dict[str, Any] | None:
    lock = "FOR UPDATE OF r" if for_update else ""
    return connection.execute(
        f"""
        SELECT {BATCH_COLUMNS}
        FROM roast_batches r JOIN green_coffees g ON g.id = r.green_coffee_id
        WHERE r.id = %s {lock}
        """,
        (roast_batch_id,),
    ).fetchone()


def list_roast_batches(
    connection: Connection, start_date: date, end_date: date, statuses: list[str], today: date
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT {BATCH_COLUMNS}, %(today)s - r.roast_date AS days_since_roast
        FROM roast_batches r JOIN green_coffees g ON g.id = r.green_coffee_id
        WHERE r.roast_date BETWEEN %(start)s AND %(end)s AND r.status = ANY(%(statuses)s)
        ORDER BY r.roast_date DESC, r.id DESC
        """,
        {"start": start_date, "end": end_date, "statuses": statuses, "today": today},
    ).fetchall()


def list_stale_roast_batches(connection: Connection, today: date, alert_days: int) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT {BATCH_COLUMNS}, %(today)s - r.roast_date AS days_since_roast
        FROM roast_batches r JOIN green_coffees g ON g.id = r.green_coffee_id
        WHERE r.status = 'OPEN' AND r.stock_kg > 0 AND %(today)s - r.roast_date > %(alert_days)s
        ORDER BY r.roast_date, r.id
        """,
        {"today": today, "alert_days": alert_days},
    ).fetchall()


def is_roast_batch_open(connection: Connection, roast_batch_id: int) -> bool:
    row = connection.execute("SELECT status FROM roast_batches WHERE id = %s", (roast_batch_id,)).fetchone()
    return row is not None and row["status"] == "OPEN"


def close_roast_batch(connection: Connection, roast_batch_id: int) -> None:
    connection.execute("UPDATE roast_batches SET status = 'CLOSED', closed_at = now() WHERE id = %s", (roast_batch_id,))


def smallest_compatible_bag_g(connection: Connection, green_coffee_id: int, roast_profile: str) -> int | None:
    return connection.execute(
        """
        SELECT MIN(weight_g) AS weight_g FROM products
        WHERE is_active AND green_coffee_id = %s AND roast_profile = %s
        """,
        (green_coffee_id, roast_profile),
    ).fetchone()["weight_g"]


PRODUCT_COLUMNS = """
    p.id, p.sku, p.sku || ' · ' || p.name AS label, p.green_coffee_id, p.roast_profile, p.weight_g,
    p.bag_id, p.label_id, p.stock, p.is_active
"""


def list_packable_products(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(f"SELECT {PRODUCT_COLUMNS} FROM products p WHERE p.is_active ORDER BY p.sku").fetchall()


def find_packing_product(connection: Connection, product_id: int) -> dict[str, Any] | None:
    return connection.execute(f"SELECT {PRODUCT_COLUMNS} FROM products p WHERE p.id = %s", (product_id,)).fetchone()


def list_compatible_batches(
    connection: Connection, green_coffee_id: int, roast_profile: str, today: date
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT {BATCH_COLUMNS}, %(today)s - r.roast_date AS days_since_roast
        FROM roast_batches r JOIN green_coffees g ON g.id = r.green_coffee_id
        WHERE r.status = 'OPEN' AND r.stock_kg > 0 AND r.green_coffee_id = %(coffee)s AND r.roast_profile = %(profile)s
        ORDER BY r.roast_date, r.id
        """,
        {"coffee": green_coffee_id, "profile": roast_profile, "today": today},
    ).fetchall()


PACKING_COLUMNS = """
    k.id, k.code, k.packing_date, k.expiry_date, k.bag_count, k.consumed_kg, k.coffee_unit_cost, k.bag_unit_cost,
    k.label_unit_cost, k.unit_cost, k.days_since_roast, k.user_email, r.code AS roast_batch_code,
    p.sku AS product_sku, p.sku || ' · ' || p.name AS product_label
"""

PACKING_JOINS = """
    JOIN roast_batches r ON r.id = k.roast_batch_id
    JOIN products p ON p.id = k.product_id
"""


def list_packing_batches(connection: Connection, start_date: date, end_date: date) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT {PACKING_COLUMNS} FROM packing_batches k {PACKING_JOINS}
        WHERE k.packing_date BETWEEN %s AND %s
        ORDER BY k.packing_date DESC, k.id DESC
        """,
        (start_date, end_date),
    ).fetchall()


def list_batch_packings(connection: Connection, roast_batch_id: int) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT {PACKING_COLUMNS} FROM packing_batches k {PACKING_JOINS}
        WHERE k.roast_batch_id = %s
        ORDER BY k.id
        """,
        (roast_batch_id,),
    ).fetchall()
