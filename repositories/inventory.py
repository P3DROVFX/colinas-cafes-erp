from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection, sql

from domain.inventory import StockBalance, StockItemKind, StockItemRef


@dataclass(frozen=True, slots=True)
class StockTable:
    table: str
    movement_column: str
    stock_column: str
    cost_column: str
    label: str
    min_stock: str
    is_active: str


ROAST_BATCH_LABEL = (
    "roast_batches.code || ' · ' || (SELECT gc.code FROM green_coffees gc WHERE gc.id = roast_batches.green_coffee_id)"
)

STOCK_TABLES: dict[StockItemKind, StockTable] = {
    StockItemKind.GREEN_COFFEE: StockTable(
        "green_coffees", "green_coffee_id", "stock_kg", "avg_cost_per_kg", "code || ' · ' || name", "min_stock_kg",
        "is_active",
    ),
    StockItemKind.ROAST_BATCH: StockTable(
        "roast_batches", "roast_batch_id", "stock_kg", "cost_per_kg", ROAST_BATCH_LABEL, "NULL::numeric",
        "status = 'OPEN'",
    ),
    StockItemKind.PACKAGING_ITEM: StockTable(
        "packaging_items", "packaging_item_id", "stock", "avg_unit_cost", "name", "min_stock", "is_active"
    ),
    StockItemKind.PRODUCT: StockTable(
        "products", "product_id", "stock", "avg_unit_cost", "sku || ' · ' || name", "min_stock", "is_active"
    ),
}  # fmt: skip

MOVEMENT_ITEM_LABEL = """
    COALESCE(g.code || ' · ' || g.name, r.code || ' · ' || rg.code, pk.name, pr.sku || ' · ' || pr.name) AS item_label,
    CASE WHEN m.green_coffee_id IS NOT NULL THEN 'GREEN_COFFEE'
         WHEN m.roast_batch_id IS NOT NULL THEN 'ROAST_BATCH'
         WHEN m.packaging_item_id IS NOT NULL THEN 'PACKAGING_ITEM'
         ELSE 'PRODUCT' END AS item_kind
"""

MOVEMENT_ITEM_JOINS = """
    LEFT JOIN green_coffees g ON g.id = m.green_coffee_id
    LEFT JOIN roast_batches r ON r.id = m.roast_batch_id
    LEFT JOIN green_coffees rg ON rg.id = r.green_coffee_id
    LEFT JOIN packaging_items pk ON pk.id = m.packaging_item_id
    LEFT JOIN products pr ON pr.id = m.product_id
"""


def _table(item_kind: StockItemKind) -> StockTable:
    return STOCK_TABLES[item_kind]


def find_stock_balance(connection: Connection, item: StockItemRef, for_update: bool = False) -> StockBalance | None:
    table = _table(item.kind)
    query = sql.SQL("SELECT {label} AS label, {stock} AS stock, {cost} AS unit_cost FROM {table} WHERE id = %s {lock}")
    row = connection.execute(
        query.format(
            label=sql.SQL(table.label),
            stock=sql.Identifier(table.stock_column),
            cost=sql.Identifier(table.cost_column),
            table=sql.Identifier(table.table),
            lock=sql.SQL("FOR UPDATE" if for_update else ""),
        ),
        (item.id,),
    ).fetchone()
    if row is None:
        return None
    return StockBalance(item, row["label"], Decimal(row["stock"]), Decimal(row["unit_cost"]))


def update_stock_balance(connection: Connection, item: StockItemRef, stock: Decimal, unit_cost: Decimal) -> None:
    table = _table(item.kind)
    query = sql.SQL("UPDATE {table} SET {stock} = %s, {cost} = %s WHERE id = %s").format(
        table=sql.Identifier(table.table),
        stock=sql.Identifier(table.stock_column),
        cost=sql.Identifier(table.cost_column),
    )
    connection.execute(query, (stock, unit_cost, item.id))


def insert_movement(connection: Connection, item: StockItemRef, values: dict[str, Any]) -> int:
    columns = {**values, _table(item.kind).movement_column: item.id}
    query = sql.SQL("INSERT INTO stock_movements ({}) VALUES ({}) RETURNING id").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() * len(columns)),
    )
    return connection.execute(query, list(columns.values())).fetchone()["id"]


def list_stock_positions(connection: Connection, item_kind: StockItemKind) -> list[dict[str, Any]]:
    table = _table(item_kind)
    query = sql.SQL(
        """
        SELECT id, {label} AS label, {stock} AS stock, {min_stock} AS min_stock, {cost} AS unit_cost,
               location, {is_active} AS is_active
        FROM {table}
        WHERE {is_active} OR {stock} <> 0
        ORDER BY label
        """
    ).format(
        label=sql.SQL(table.label),
        stock=sql.Identifier(table.stock_column),
        min_stock=sql.SQL(table.min_stock),
        cost=sql.Identifier(table.cost_column),
        is_active=sql.SQL(table.is_active),
        table=sql.Identifier(table.table),
    )
    return connection.execute(query).fetchall()


def list_stock_items(connection: Connection, item_kind: StockItemKind) -> list[dict[str, Any]]:
    table = _table(item_kind)
    query = sql.SQL("SELECT id, {label} AS label, {is_active} AS is_active FROM {table} ORDER BY label").format(
        label=sql.SQL(table.label), is_active=sql.SQL(table.is_active), table=sql.Identifier(table.table)
    )
    return connection.execute(query).fetchall()


def list_item_movements(
    connection: Connection, item: StockItemRef, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    query = sql.SQL(
        """
        SELECT id, movement_date, movement_type, quantity, unit_cost, total_value, balance_after,
               source_module, source_id, reason, notes, user_email, created_at
        FROM stock_movements
        WHERE {column} = %s AND movement_date BETWEEN %s AND %s
        ORDER BY id DESC
        """
    ).format(column=sql.Identifier(_table(item.kind).movement_column))
    return connection.execute(query, (item.id, start_date, end_date)).fetchall()


def list_source_movements(
    connection: Connection, source_module: str, source_id: int, movement_types: list[str] | None = None
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT m.id, m.movement_date, m.movement_type, m.quantity, m.unit_cost, m.total_value, m.balance_after,
               {MOVEMENT_ITEM_LABEL}
        FROM stock_movements m
        {MOVEMENT_ITEM_JOINS}
        WHERE m.source_module = %s AND m.source_id = %s
          AND (%s::text[] IS NULL OR m.movement_type = ANY(%s::text[]))
        ORDER BY m.id
        """,
        (source_module, source_id, movement_types, movement_types),
    ).fetchall()
