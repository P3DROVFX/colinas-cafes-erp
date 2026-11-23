from psycopg import Connection


def find_setting_value(connection: Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else None


def find_setting_values(connection: Connection, keys: list[str]) -> dict[str, str | None]:
    rows = connection.execute("SELECT key, value FROM settings WHERE key = ANY(%s)", (keys,)).fetchall()
    return {row["key"]: row["value"] for row in rows}


def list_settings(connection: Connection) -> list[dict]:
    return connection.execute(
        "SELECT key, value, value_type, description, updated_at, updated_by FROM settings ORDER BY key"
    ).fetchall()


def update_setting(connection: Connection, key: str, value: str | None) -> None:
    connection.execute("UPDATE settings SET value = %s WHERE key = %s", (value, key))
