from psycopg import Connection


def find_setting_value(connection: Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else None


def find_setting_values(connection: Connection, keys: list[str]) -> dict[str, str | None]:
    rows = connection.execute("SELECT key, value FROM settings WHERE key = ANY(%s)", (keys,)).fetchall()
    return {row["key"]: row["value"] for row in rows}
