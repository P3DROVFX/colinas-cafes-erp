from datetime import date
from typing import Any

from psycopg import Connection

ENTRY_COLUMNS = """
    e.id, e.entry_type, e.description, e.amount, e.accrual_date, e.due_date, e.installment, e.installment_count,
    e.status, e.settled_date, e.source_module, e.source_id, e.cancel_reason, c.name AS category_name,
    COALESCE(s.name, cu.name) AS counterparty,
    CASE WHEN e.status = 'PENDING' AND e.due_date < %(today)s THEN 'OVERDUE' ELSE e.status END AS display_status
"""

ENTRY_JOINS = """
    JOIN financial_categories c ON c.id = e.category_id
    LEFT JOIN suppliers s ON s.id = e.supplier_id
    LEFT JOIN customers cu ON cu.id = e.customer_id
"""


def find_system_category_id(connection: Connection, name: str) -> int | None:
    row = connection.execute("SELECT id FROM financial_categories WHERE name = %s AND is_system", (name,)).fetchone()
    return row["id"] if row else None


def insert_entry(connection: Connection, values: dict[str, Any]) -> int:
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({column})s" for column in values)
    return connection.execute(
        f"INSERT INTO financial_entries ({columns}) VALUES ({placeholders}) RETURNING id", values
    ).fetchone()["id"]


def list_source_entries(connection: Connection, source_module: str, source_id: int, today: date) -> list[dict]:
    return connection.execute(
        f"""
        SELECT {ENTRY_COLUMNS}
        FROM financial_entries e {ENTRY_JOINS}
        WHERE e.source_module = %(module)s AND e.source_id = %(source_id)s
        ORDER BY e.installment, e.id
        """,
        {"module": source_module, "source_id": source_id, "today": today},
    ).fetchall()


def count_settled_source_entries(connection: Connection, source_module: str, source_id: int) -> int:
    return connection.execute(
        """
        SELECT count(*) AS total FROM financial_entries
        WHERE source_module = %s AND source_id = %s AND status = 'SETTLED'
        """,
        (source_module, source_id),
    ).fetchone()["total"]


def cancel_source_entries(
    connection: Connection, source_module: str, source_id: int, reason: str, user_email: str
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        UPDATE financial_entries
        SET status = 'CANCELLED', cancel_reason = %s, cancelled_by = %s, cancelled_at = now()
        WHERE source_module = %s AND source_id = %s AND status = 'PENDING'
        RETURNING id, entry_type, description, amount, due_date
        """,
        (reason, user_email, source_module, source_id),
    ).fetchall()


def list_entries(
    connection: Connection,
    today: date,
    due_from: date,
    due_to: date,
    entry_type: str | None,
    display_statuses: list[str],
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT * FROM (
            SELECT {ENTRY_COLUMNS}
            FROM financial_entries e {ENTRY_JOINS}
            WHERE e.due_date BETWEEN %(due_from)s AND %(due_to)s
              AND (%(entry_type)s::text IS NULL OR e.entry_type = %(entry_type)s)
        ) entries
        WHERE display_status = ANY(%(statuses)s)
        ORDER BY due_date, id
        """,
        {
            "today": today,
            "due_from": due_from,
            "due_to": due_to,
            "entry_type": entry_type,
            "statuses": display_statuses,
        },
    ).fetchall()
