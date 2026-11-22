import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from core import db
from scripts.migrate import apply_migrations


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not conninfo_to_dict(url).get("dbname", "").endswith("_test"):
        pytest.exit("TEST_DATABASE_URL must point to a database whose name ends with '_test'")
    with psycopg.connect(url) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")
        connection.commit()
        apply_migrations(connection)
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    yield url
    db.close_pool()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url


@pytest.fixture(autouse=True)
def clean_users(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("TRUNCATE users RESTART IDENTITY CASCADE")
