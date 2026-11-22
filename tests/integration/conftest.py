import os

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict

from core import db
from domain.access import Role, User
from scripts.migrate import apply_migrations

BASELINE_SCHEMA = "test_baseline"


def _application_tables(connection: Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'schema_migrations'
        ORDER BY tablename
        """
    ).fetchall()
    return [row[0] for row in rows]


def _snapshot_reference_data(connection: Connection) -> list[str]:
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(BASELINE_SCHEMA)))
    reference_tables = []
    for table in _application_tables(connection):
        has_rows = connection.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(sql.Identifier(table)))
        if has_rows.fetchone()[0]:
            connection.execute(
                sql.SQL("CREATE TABLE {} AS TABLE {}").format(
                    sql.Identifier(BASELINE_SCHEMA, table), sql.Identifier("public", table)
                )
            )
            reference_tables.append(table)
    return reference_tables


def _restore_reference_data(connection: Connection, reference_tables: list[str]) -> None:
    tables = sql.SQL(", ").join(sql.Identifier("public", table) for table in _application_tables(connection))
    connection.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(tables))
    for table in reference_tables:
        connection.execute(
            sql.SQL("INSERT INTO {} OVERRIDING SYSTEM VALUE SELECT * FROM {}").format(
                sql.Identifier("public", table), sql.Identifier(BASELINE_SCHEMA, table)
            )
        )
        row = connection.execute(
            """
            SELECT pg_get_serial_sequence('public.' || table_name, 'id') FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = 'id'
            """,
            (table,),
        ).fetchone()
        if row and row[0]:
            connection.execute(
                sql.SQL("SELECT setval(%s, (SELECT max(id) FROM {}))").format(sql.Identifier("public", table)),
                (row[0],),
            )


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not conninfo_to_dict(url).get("dbname", "").endswith("_test"):
        pytest.exit("TEST_DATABASE_URL must point to a database whose name ends with '_test'")
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    yield url
    db.close_pool()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url


@pytest.fixture(scope="session")
def reference_tables(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(BASELINE_SCHEMA)))
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")
        connection.commit()
        apply_migrations(connection)
        tables = _snapshot_reference_data(connection)
    return tables


@pytest.fixture(autouse=True)
def clean_database(database_url, reference_tables):
    with psycopg.connect(database_url) as connection:
        _restore_reference_data(connection, reference_tables)


@pytest.fixture
def make_user(database_url):
    def factory(role: Role) -> User:
        email = f"{role.value.lower()}@colinas.com.br"
        with psycopg.connect(database_url) as connection:
            user_id = connection.execute(
                "INSERT INTO users (email, name, role) VALUES (%s, %s, %s) RETURNING id",
                (email, role.value.title(), role.value),
            ).fetchone()[0]
        return User(id=user_id, email=email, name=role.value.title(), role=role, is_active=True)

    return factory
