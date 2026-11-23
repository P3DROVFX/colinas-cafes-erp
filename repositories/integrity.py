from typing import Any

from psycopg import Connection, sql

from domain.inventory import StockItemKind
from repositories.inventory import STOCK_TABLES


def stock_differs_from_movements(connection: Connection, item_kind: StockItemKind) -> list[dict[str, Any]]:
    table = STOCK_TABLES[item_kind]
    query = sql.SQL(
        """
        SELECT {label} AS item, t.{stock} AS stock, COALESCE(SUM(m.quantity), 0) AS movements_total
        FROM {table} t
        LEFT JOIN stock_movements m ON m.{column} = t.id
        GROUP BY t.id
        HAVING t.{stock} <> COALESCE(SUM(m.quantity), 0)
        """
    ).format(
        label=sql.SQL(table.label),
        stock=sql.Identifier(table.stock_column),
        table=sql.Identifier(table.table),
        column=sql.Identifier(table.movement_column),
    )
    return connection.execute(query).fetchall()


def last_balance_differs_from_stock(connection: Connection, item_kind: StockItemKind) -> list[dict[str, Any]]:
    table = STOCK_TABLES[item_kind]
    query = sql.SQL(
        """
        SELECT {label} AS item, t.{stock} AS stock, last.balance_after
        FROM {table} t
        JOIN LATERAL (
            SELECT balance_after FROM stock_movements m WHERE m.{column} = t.id ORDER BY m.id DESC LIMIT 1
        ) last ON TRUE
        WHERE last.balance_after <> t.{stock}
        """
    ).format(
        label=sql.SQL(table.label),
        stock=sql.Identifier(table.stock_column),
        table=sql.Identifier(table.table),
        column=sql.Identifier(table.movement_column),
    )
    return connection.execute(query).fetchall()


def received_purchases_with_wrong_payables(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT p.number AS item, p.total_amount, p.installments,
               COALESCE(SUM(e.amount), 0) AS entries_total, count(e.id) AS entries_count
        FROM purchases p
        LEFT JOIN financial_entries e
          ON e.source_module = 'PURCHASES' AND e.source_id = p.id AND e.status <> 'CANCELLED'
        WHERE p.status = 'RECEIVED'
        GROUP BY p.id
        HAVING COALESCE(SUM(e.amount), 0) <> p.total_amount OR count(e.id) <> p.installments
        """
    ).fetchall()
