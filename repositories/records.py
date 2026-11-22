from collections.abc import Mapping
from enum import Enum, StrEnum
from typing import Any

from psycopg import Connection, sql


class MasterTable(StrEnum):
    SUPPLIERS = "suppliers"
    FARMS = "farms"
    GREEN_COFFEES = "green_coffees"
    PACKAGING_ITEMS = "packaging_items"
    PRODUCTS = "products"
    CUSTOMERS = "customers"
    FINANCIAL_CATEGORIES = "financial_categories"
    FINANCIAL_ACCOUNTS = "financial_accounts"


def _adapt(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def find_record_for_update(connection: Connection, table: MasterTable, record_id: int) -> dict[str, Any] | None:
    query = sql.SQL("SELECT * FROM {} WHERE id = %s FOR UPDATE").format(sql.Identifier(table))
    return connection.execute(query, (record_id,)).fetchone()


def insert_record(connection: Connection, table: MasterTable, values: Mapping[str, Any]) -> int:
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    return connection.execute(query, [_adapt(value) for value in values.values()]).fetchone()["id"]


def update_record(connection: Connection, table: MasterTable, record_id: int, values: Mapping[str, Any]) -> None:
    query = sql.SQL("UPDATE {} SET {} WHERE id = %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(column)) for column in values),
    )
    connection.execute(query, [*(_adapt(value) for value in values.values()), record_id])


def delete_record(connection: Connection, table: MasterTable, record_id: int) -> None:
    query = sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table))
    connection.execute(query, (record_id,))


def set_record_active(connection: Connection, table: MasterTable, record_id: int, is_active: bool) -> None:
    query = sql.SQL("UPDATE {} SET is_active = %s WHERE id = %s").format(sql.Identifier(table))
    connection.execute(query, (is_active, record_id))


def search_pattern(search: str) -> str:
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_filters(search: str, include_inactive: bool) -> dict[str, Any]:
    search = search.strip()
    digits = "".join(character for character in search if character.isdigit())
    return {
        "search": search,
        "pattern": search_pattern(search),
        "digits_pattern": f"%{digits}%" if digits else None,
        "include_inactive": include_inactive,
    }
