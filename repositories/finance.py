from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection

ENTRY_COLUMNS = """
    e.id, e.entry_type, e.description, e.amount, e.accrual_date, e.due_date, e.installment, e.installment_count,
    e.status, e.settled_date, e.source_module, e.source_id, e.cancel_reason, c.name AS category_name,
    COALESCE(s.name, cu.name) AS counterparty, e.account_id, fa.name AS account_name, e.settlement_method,
    e.is_reconciled, e.reconciled_date,
    CASE WHEN e.status = 'PENDING' AND e.due_date < %(today)s THEN 'OVERDUE' ELSE e.status END AS display_status
"""

ENTRY_JOINS = """
    JOIN financial_categories c ON c.id = e.category_id
    LEFT JOIN suppliers s ON s.id = e.supplier_id
    LEFT JOIN customers cu ON cu.id = e.customer_id
    LEFT JOIN financial_accounts fa ON fa.id = e.account_id
"""


def find_system_category_id(connection: Connection, name: str) -> int | None:
    row = connection.execute("SELECT id FROM financial_categories WHERE name = %s AND is_system", (name,)).fetchone()
    return row["id"] if row else None


def insert_entry(connection: Connection, values: dict[str, Any]) -> int:
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({column})s" for column in values)
    return connection.execute(
        f"INSERT INTO financial_entries ({columns}) VALUES ({placeholders}) RETURNING id", values
    ).fetchone()["id"]


def list_source_entries(connection: Connection, source_module: str, source_id: int, today: date) -> list[dict]:
    return connection.execute(
        f"""
        SELECT {ENTRY_COLUMNS}
        FROM financial_entries e {ENTRY_JOINS}
        WHERE e.source_module = %(module)s AND e.source_id = %(source_id)s
        ORDER BY e.installment, e.id
        """,
        {"module": source_module, "source_id": source_id, "today": today},
    ).fetchall()


def count_settled_source_entries(connection: Connection, source_module: str, source_id: int) -> int:
    return connection.execute(
        """
        SELECT count(*) AS total FROM financial_entries
        WHERE source_module = %s AND source_id = %s AND status = 'SETTLED'
        """,
        (source_module, source_id),
    ).fetchone()["total"]


def cancel_source_entries(
    connection: Connection, source_module: str, source_id: int, reason: str, user_email: str
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        UPDATE financial_entries
        SET status = 'CANCELLED', cancel_reason = %s, cancelled_by = %s, cancelled_at = now()
        WHERE source_module = %s AND source_id = %s AND status = 'PENDING'
        RETURNING id, entry_type, description, amount, due_date
        """,
        (reason, user_email, source_module, source_id),
    ).fetchall()


def list_entries(
    connection: Connection,
    today: date,
    due_from: date,
    due_to: date,
    entry_type: str | None,
    display_statuses: list[str],
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT * FROM (
            SELECT {ENTRY_COLUMNS}
            FROM financial_entries e {ENTRY_JOINS}
            WHERE e.due_date BETWEEN %(due_from)s AND %(due_to)s
              AND (%(entry_type)s::text IS NULL OR e.entry_type = %(entry_type)s)
        ) entries
        WHERE display_status = ANY(%(statuses)s)
        ORDER BY due_date, id
        """,
        {
            "today": today,
            "due_from": due_from,
            "due_to": due_to,
            "entry_type": entry_type,
            "statuses": display_statuses,
        },
    ).fetchall()


def find_system_account_id(connection: Connection, kind: str) -> int | None:
    row = connection.execute(
        "SELECT id FROM financial_accounts WHERE kind = %s AND is_system ORDER BY id LIMIT 1", (kind,)
    ).fetchone()
    return row["id"] if row else None


def list_settled_source_entries(
    connection: Connection, source_module: str, source_id: int, entry_type: str
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, amount, description FROM financial_entries
        WHERE source_module = %s AND source_id = %s AND entry_type = %s AND status = 'SETTLED'
        """,
        (source_module, source_id, entry_type),
    ).fetchall()


def find_entries(connection: Connection, entry_ids: list[int], for_update: bool = False) -> list[dict[str, Any]]:
    lock = "FOR UPDATE" if for_update else ""
    return connection.execute(
        f"""
        SELECT id, entry_type, description, amount, accrual_date, due_date, status, is_reconciled, source_module,
               account_id
        FROM financial_entries WHERE id = ANY(%s) ORDER BY id {lock}
        """,
        (entry_ids,),
    ).fetchall()


def settle_entry(
    connection: Connection, entry_id: int, settled_date: date, account_id: int, method: str, user_email: str
) -> None:
    connection.execute(
        """
        UPDATE financial_entries
        SET status = 'SETTLED', settled_date = %s, account_id = %s, settlement_method = %s, settled_by = %s,
            settled_at = now()
        WHERE id = %s
        """,
        (settled_date, account_id, method, user_email, entry_id),
    )


def reverse_settlement(connection: Connection, entry_id: int) -> None:
    connection.execute(
        """
        UPDATE financial_entries
        SET status = 'PENDING', settled_date = NULL, account_id = NULL, settlement_method = NULL, settled_by = NULL,
            settled_at = NULL
        WHERE id = %s
        """,
        (entry_id,),
    )


def cancel_entry(connection: Connection, entry_id: int, reason: str, user_email: str) -> None:
    connection.execute(
        """
        UPDATE financial_entries
        SET status = 'CANCELLED', cancel_reason = %s, cancelled_by = %s, cancelled_at = now()
        WHERE id = %s
        """,
        (reason, user_email, entry_id),
    )


def set_reconciled(connection: Connection, entry_ids: list[int], reconciled_date: date | None) -> None:
    connection.execute(
        """
        UPDATE financial_entries SET is_reconciled = %s, reconciled_date = %s
        WHERE id = ANY(%s) AND status = 'SETTLED'
        """,
        (reconciled_date is not None, reconciled_date, entry_ids),
    )


def find_category(connection: Connection, category_id: int) -> dict[str, Any] | None:
    return connection.execute(
        "SELECT id, name, entry_type, dre_group, is_active FROM financial_categories WHERE id = %s", (category_id,)
    ).fetchone()


def list_manual_categories(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, entry_type, dre_group FROM financial_categories
        WHERE is_active AND dre_group IN ('OPERATING_EXPENSE', 'OTHER_REVENUE')
        ORDER BY entry_type, name
        """
    ).fetchall()


def find_account(connection: Connection, account_id: int) -> dict[str, Any] | None:
    return connection.execute(
        "SELECT id, name, kind, opening_balance, opening_date, is_active FROM financial_accounts WHERE id = %s",
        (account_id,),
    ).fetchone()


def list_account_balances(connection: Connection, as_of: date) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT a.id, a.name, a.kind, a.opening_balance, a.opening_date, a.is_active,
               a.opening_balance + COALESCE(SUM(CASE WHEN e.entry_type = 'RECEIVABLE' THEN e.amount ELSE -e.amount END)
                 FILTER (WHERE e.settled_date <= %(as_of)s), 0) AS system_balance,
               a.opening_balance + COALESCE(SUM(CASE WHEN e.entry_type = 'RECEIVABLE' THEN e.amount ELSE -e.amount END)
                 FILTER (WHERE e.is_reconciled AND e.settled_date <= %(as_of)s), 0) AS reconciled_balance,
               count(e.id) FILTER (WHERE NOT e.is_reconciled AND e.settled_date <= %(as_of)s) AS unreconciled_count
        FROM financial_accounts a
        LEFT JOIN financial_entries e ON e.account_id = a.id AND e.status = 'SETTLED'
        GROUP BY a.id
        ORDER BY a.is_active DESC, a.name
        """,
        {"as_of": as_of},
    ).fetchall()


def list_settled_entries(
    connection: Connection, account_ids: list[int], start_date: date, end_date: date
) -> list[dict[str, Any]]:
    return connection.execute(
        f"""
        SELECT {ENTRY_COLUMNS}
        FROM financial_entries e {ENTRY_JOINS}
        WHERE e.status = 'SETTLED' AND e.account_id = ANY(%(accounts)s)
          AND e.settled_date BETWEEN %(start)s AND %(end)s
        ORDER BY e.settled_date, e.id
        """,
        {"accounts": account_ids, "start": start_date, "end": end_date, "today": end_date},
    ).fetchall()


def settled_total_before(connection: Connection, account_ids: list[int], before: date) -> Decimal:
    return connection.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN entry_type = 'RECEIVABLE' THEN amount ELSE -amount END), 0) AS total
        FROM financial_entries
        WHERE status = 'SETTLED' AND account_id = ANY(%s) AND settled_date < %s
        """,
        (account_ids, before),
    ).fetchone()["total"]


def list_pending_entries(connection: Connection, due_until: date) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, entry_type, amount, due_date FROM financial_entries
        WHERE status = 'PENDING' AND due_date <= %s
        ORDER BY due_date
        """,
        (due_until,),
    ).fetchall()


def open_entries_summary(connection: Connection, today: date, due_until: date) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT entry_type,
               COALESCE(SUM(amount) FILTER (WHERE due_date < %(today)s), 0) AS overdue_amount,
               count(*) FILTER (WHERE due_date < %(today)s) AS overdue_count,
               COALESCE(SUM(amount) FILTER (WHERE due_date BETWEEN %(today)s AND %(until)s), 0) AS due_soon_amount,
               count(*) FILTER (WHERE due_date BETWEEN %(today)s AND %(until)s) AS due_soon_count
        FROM financial_entries
        WHERE status = 'PENDING'
        GROUP BY entry_type
        """,
        {"today": today, "until": due_until},
    ).fetchall()
