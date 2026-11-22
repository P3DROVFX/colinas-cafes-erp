import sys
from pathlib import Path

import psycopg

from core.config import PROJECT_ROOT, get_database_url

MIGRATIONS_DIR = PROJECT_ROOT / "sql"


def list_migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def apply_migrations(connection: psycopg.Connection) -> list[str]:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    connection.commit()
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    newly_applied = []
    for path in list_migration_files():
        if path.name in applied:
            continue
        with connection.transaction():
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
        newly_applied.append(path.name)
    return newly_applied


def main() -> int:
    with psycopg.connect(get_database_url()) as connection:
        newly_applied = apply_migrations(connection)
    if newly_applied:
        for name in newly_applied:
            print(f"applied {name}")
    else:
        print("database is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
