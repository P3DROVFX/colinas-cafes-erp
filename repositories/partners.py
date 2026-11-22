from typing import Any

from psycopg import Connection

from domain.partners import SupplyType
from repositories.records import list_filters


def list_suppliers(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, person_type, document, supply_type, email, phone, city, state, lead_time_days, is_active
        FROM suppliers
        WHERE (%(include_inactive)s OR is_active)
          AND (%(search)s = '' OR name ILIKE %(pattern)s OR city ILIKE %(pattern)s
               OR document LIKE %(digits_pattern)s)
        ORDER BY name
        """,
        list_filters(search, include_inactive),
    ).fetchall()


def list_supplier_options(
    connection: Connection, supply_type: SupplyType, include_id: int | None = None
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name FROM suppliers
        WHERE supply_type = %s AND (is_active OR id = %s)
        ORDER BY name
        """,
        (supply_type.value, include_id),
    ).fetchall()


def find_supplier_supply_type(connection: Connection, supplier_id: int) -> SupplyType | None:
    row = connection.execute("SELECT supply_type FROM suppliers WHERE id = %s", (supplier_id,)).fetchone()
    return SupplyType(row["supply_type"]) if row else None


def list_customers(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, person_type, document, segment, email, phone, address, city, state,
               payment_term_days, credit_limit, is_system, is_active
        FROM customers
        WHERE (%(include_inactive)s OR is_active)
          AND (%(search)s = '' OR name ILIKE %(pattern)s OR email ILIKE %(pattern)s OR city ILIKE %(pattern)s
               OR document LIKE %(digits_pattern)s)
        ORDER BY is_system DESC, name
        """,
        list_filters(search, include_inactive),
    ).fetchall()
