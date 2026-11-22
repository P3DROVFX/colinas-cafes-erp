from psycopg import Connection


def find_setting_value(connection: Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else None
