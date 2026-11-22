import psycopg

from scripts.migrate import apply_migrations, list_migration_files


def test_all_migrations_are_recorded(database_url):
    with psycopg.connect(database_url) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [path.name for path in list_migration_files()]


def test_applying_migrations_twice_is_a_no_op(database_url):
    with psycopg.connect(database_url) as connection:
        assert apply_migrations(connection) == []


def test_reference_data_is_loaded(database_url):
    with psycopg.connect(database_url) as connection:
        system_categories = connection.execute("SELECT count(*) FROM financial_categories WHERE is_system").fetchone()[
            0
        ]
        generic_customer = connection.execute(
            "SELECT count(*) FROM customers WHERE name = 'Consumidor Final'"
        ).fetchone()[0]
    assert system_categories == 8
    assert generic_customer == 1
