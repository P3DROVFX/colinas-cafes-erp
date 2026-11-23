from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


def insert_audit(
    connection: Connection,
    table_name: str,
    action: str,
    old_data: dict[str, Any] | None,
    new_data: dict[str, Any] | None,
    user_email: str,
    record_id: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_email)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (table_name, record_id, action, Jsonb(old_data), Jsonb(new_data), user_email),
    )


def list_audit(connection: Connection, table_name: str, limit: int = 50) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT action, old_data, new_data, user_email, created_at FROM audit_log
        WHERE table_name = %s ORDER BY id DESC LIMIT %s
        """,
        (table_name, limit),
    ).fetchall()
