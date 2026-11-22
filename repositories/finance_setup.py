from typing import Any

from psycopg import Connection

from repositories.records import list_filters


def list_financial_categories(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, entry_type, dre_group, is_system, is_active
        FROM financial_categories
        WHERE (%(include_inactive)s OR is_active) AND (%(search)s = '' OR name ILIKE %(pattern)s)
        ORDER BY entry_type DESC, dre_group, name
        """,
        list_filters(search, include_inactive),
    ).fetchall()


def list_financial_accounts(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, kind, opening_balance, opening_date, is_system, is_active
        FROM financial_accounts
        WHERE (%(include_inactive)s OR is_active) AND (%(search)s = '' OR name ILIKE %(pattern)s)
        ORDER BY name
        """,
        list_filters(search, include_inactive),
    ).fetchall()
