from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from threading import Lock
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core.clock import TIMEZONE_NAME
from core.config import get_database_url

Params = Sequence[Any] | Mapping[str, Any] | None

_pool: ConnectionPool | None = None
_pool_lock = Lock()


def _configure_connection(connection: Connection) -> None:
    connection.execute(f"SET TIME ZONE '{TIMEZONE_NAME}'")
    connection.commit()


def get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                conninfo=get_database_url(),
                min_size=1,
                max_size=4,
                kwargs={"row_factory": dict_row},
                configure=_configure_connection,
                open=True,
            )
        return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def transaction(user_email: str) -> Iterator[Connection]:
    """Commits on normal exit and rolls back on any exception."""
    with get_pool().connection() as connection:
        connection.execute("SELECT set_config('app.user_email', %s, true)", (user_email,))
        yield connection


def fetch_all(query: str, params: Params = None) -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        return connection.execute(query, params).fetchall()


def fetch_one(query: str, params: Params = None) -> dict[str, Any] | None:
    with get_pool().connection() as connection:
        return connection.execute(query, params).fetchone()
