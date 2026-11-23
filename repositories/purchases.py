from datetime import date
from typing import Any

from psycopg import Connection

from domain.inventory import StockItemKind
from domain.purchasing import PurchaseStatus

ITEM_LABEL = """
    COALESCE(g.code || ' · ' || g.name, pk.name) AS item_label,
    CASE WHEN i.green_coffee_id IS NOT NULL THEN 'GREEN_COFFEE' ELSE 'PACKAGING_ITEM' END AS item_kind,
    COALESCE(i.green_coffee_id, i.packaging_item_id) AS item_id
"""

ITEM_COLUMNS: dict[StockItemKind, str] = {
    StockItemKind.GREEN_COFFEE: "green_coffee_id",
    StockItemKind.PACKAGING_ITEM: "packaging_item_id",
}


def next_purchase_number(connection: Connection, year: int) -> str:
    sequence = connection.execute("SELECT nextval('purchase_number_seq') AS value").fetchone()["value"]
    return f"C-{year}-{sequence:06d}"


def insert_purchase(connection: Connection, values: dict[str, Any]) -> int:
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({column})s" for column in values)
    return connection.execute(
        f"INSERT INTO purchases ({columns}) VALUES ({placeholders}) RETURNING id", values
    ).fetchone()["id"]


def update_purchase(connection: Connection, purchase_id: int, values: dict[str, Any]) -> None:
    assignments = ", ".join(f"{column} = %({column})s" for column in values)
    connection.execute(
        f"UPDATE purchases SET {assignments} WHERE id = %(purchase_id)s", {**values, "purchase_id": purchase_id}
    )


def insert_purchase_item(
    connection: Connection, purchase_id: int, kind: StockItemKind, item_id: int, quantity, unit_cost
) -> None:
    column = ITEM_COLUMNS[kind]
    connection.execute(
        f"INSERT INTO purchase_items (purchase_id, {column}, quantity, unit_cost) VALUES (%s, %s, %s, %s)",
        (purchase_id, item_id, quantity, unit_cost),
    )


def delete_purchase_items(connection: Connection, purchase_id: int) -> None:
    connection.execute("DELETE FROM purchase_items WHERE purchase_id = %s", (purchase_id,))


def set_item_costs(connection: Connection, purchase_item_id: int, allocated_freight, effective_unit_cost) -> None:
    connection.execute(
        "UPDATE purchase_items SET allocated_freight = %s, effective_unit_cost = %s WHERE id = %s",
        (allocated_freight, effective_unit_cost, purchase_item_id),
    )


def find_purchase(connection: Connection, purchase_id: int, for_update: bool = False) -> dict[str, Any] | None:
    lock = "FOR UPDATE OF p" if for_update else ""
    return connection.execute(
        f"""
        SELECT p.*, s.name AS supplier_name, s.supply_type
        FROM purchases p JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.id = %s {lock}
        """,
        (purchase_id,),
    ).fetchone()


def list_purchase_items(connection: Connection, purchase_id: int) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT i.id, i.quantity, i.unit_cost, i.allocated_freight, i.effective_unit_cost, {ITEM_LABEL}
        FROM purchase_items i
        LEFT JOIN green_coffees g ON g.id = i.green_coffee_id
        LEFT JOIN packaging_items pk ON pk.id = i.packaging_item_id
        WHERE i.purchase_id = %s
        ORDER BY i.id
        """,
        (purchase_id,),
    ).fetchall()


def list_purchases(
    connection: Connection, start_date: date, end_date: date, supplier_id: int | None, statuses: list[str]
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT p.id, p.number, p.status, p.order_date, p.expected_date, p.received_date, p.products_amount,
               p.freight_amount, p.total_amount, p.installments, p.supplier_id, s.name AS supplier_name
        FROM purchases p JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.order_date BETWEEN %(start)s AND %(end)s
          AND (%(supplier_id)s::bigint IS NULL OR p.supplier_id = %(supplier_id)s)
          AND p.status = ANY(%(statuses)s)
        ORDER BY p.order_date DESC, p.id DESC
        """,
        {"start": start_date, "end": end_date, "supplier_id": supplier_id, "statuses": statuses},
    ).fetchall()


def find_coffee_supplier_ids(connection: Connection, green_coffee_ids: list[int]) -> dict[int, int | None]:
    rows = connection.execute(
        """
        SELECT g.id, f.supplier_id FROM green_coffees g JOIN farms f ON f.id = g.farm_id
        WHERE g.id = ANY(%s)
        """,
        (green_coffee_ids,),
    ).fetchall()
    return {row["id"]: row["supplier_id"] for row in rows}


def find_active_packaging_ids(connection: Connection, packaging_item_ids: list[int]) -> set[int]:
    rows = connection.execute(
        "SELECT id FROM packaging_items WHERE id = ANY(%s) AND is_active", (packaging_item_ids,)
    ).fetchall()
    return {row["id"] for row in rows}


def list_purchasable_coffees(connection: Connection, supplier_id: int) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT g.id, g.code || ' · ' || g.name || ' (' || g.harvest_year || ')' AS label
        FROM green_coffees g JOIN farms f ON f.id = g.farm_id
        WHERE f.supplier_id = %s AND g.is_active
        ORDER BY label
        """,
        (supplier_id,),
    ).fetchall()


def list_purchasable_packaging(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        "SELECT id, name AS label FROM packaging_items WHERE is_active ORDER BY kind, capacity_g NULLS FIRST, name"
    ).fetchall()


def mark_received(connection: Connection, purchase_id: int, received_date: date, user_email: str) -> None:
    connection.execute(
        """
        UPDATE purchases SET status = 'RECEIVED', received_date = %s, received_by = %s, received_at = now()
        WHERE id = %s
        """,
        (received_date, user_email, purchase_id),
    )


def mark_closed(connection: Connection, purchase_id: int, status: PurchaseStatus, reason: str, user_email: str) -> None:
    connection.execute(
        """
        UPDATE purchases SET status = %s, cancel_reason = %s, cancelled_by = %s, cancelled_at = now()
        WHERE id = %s
        """,
        (status.value, reason, user_email, purchase_id),
    )
