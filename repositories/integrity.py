from typing import Any

from psycopg import Connection, sql

from domain.inventory import StockItemKind
from repositories.inventory import STOCK_TABLES


def stock_differs_from_movements(connection: Connection, item_kind: StockItemKind) -> list[dict[str, Any]]:
    table = STOCK_TABLES[item_kind]
    query = sql.SQL(
        """
        SELECT {label} AS item, {table}.{stock} AS stock, COALESCE(SUM(m.quantity), 0) AS movements_total
        FROM {table}
        LEFT JOIN stock_movements m ON m.{column} = {table}.id
        GROUP BY {table}.id
        HAVING {table}.{stock} <> COALESCE(SUM(m.quantity), 0)
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
        SELECT {label} AS item, {table}.{stock} AS stock, last.balance_after
        FROM {table}
        JOIN LATERAL (
            SELECT balance_after FROM stock_movements m WHERE m.{column} = {table}.id ORDER BY m.id DESC LIMIT 1
        ) last ON TRUE
        WHERE last.balance_after <> {table}.{stock}
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


def roast_batches_with_inconsistent_status(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT r.code AS item, r.status, r.stock_kg, last.movement_date AS last_movement
        FROM roast_batches r
        LEFT JOIN LATERAL (
            SELECT movement_date FROM stock_movements m WHERE m.roast_batch_id = r.id ORDER BY m.id DESC LIMIT 1
        ) last ON TRUE
        WHERE (r.status = 'CLOSED' AND r.stock_kg <> 0)
           OR (r.status = 'OPEN' AND r.stock_kg = 0 AND COALESCE(last.movement_date, r.roast_date) < current_date - 1)
        """
    ).fetchall()


def entries_without_source_document(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT e.id AS item, e.source_module, e.source_id, e.description
        FROM financial_entries e
        WHERE (e.source_module = 'PURCHASES' AND NOT EXISTS (SELECT 1 FROM purchases p WHERE p.id = e.source_id))
           OR (e.source_module = 'PRODUCTION' AND NOT EXISTS (SELECT 1 FROM harvests h WHERE h.id = e.source_id))
           OR (e.source_module = 'SALES' AND NOT EXISTS (SELECT 1 FROM sales s WHERE s.id = e.source_id))
        """
    ).fetchall()


def packing_value_differs_from_batches(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT 'Envases' AS item, movements.total AS movements_total, batches.total AS batches_total
        FROM (SELECT COALESCE(SUM(total_value), 0) AS total FROM stock_movements WHERE movement_type = 'PACKING_IN')
             movements,
             (SELECT COALESCE(SUM(round(bag_count * unit_cost, 2)), 0) AS total FROM packing_batches) batches
        WHERE movements.total <> batches.total
        """
    ).fetchall()
