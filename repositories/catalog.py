from typing import Any

from psycopg import Connection

from domain.catalog import PackagingKind, PackagingSpec
from repositories.records import list_filters


def list_farms(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT f.id, f.name, f.city, f.state, f.altitude_m, f.producer, f.is_own, f.supplier_id,
               s.name AS supplier_name, f.is_active
        FROM farms f
        LEFT JOIN suppliers s ON s.id = f.supplier_id
        WHERE (%(include_inactive)s OR f.is_active)
          AND (%(search)s = '' OR f.name ILIKE %(pattern)s OR f.producer ILIKE %(pattern)s
               OR f.city ILIKE %(pattern)s)
        ORDER BY f.name
        """,
        list_filters(search, include_inactive),
    ).fetchall()


def list_farm_options(connection: Connection, include_id: int | None = None) -> list[dict[str, Any]]:
    return connection.execute(
        "SELECT id, name, is_own FROM farms WHERE is_active OR id = %s ORDER BY name",
        (include_id,),
    ).fetchall()


def list_green_coffees(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT g.id, g.code, g.name, g.farm_id, f.name AS farm_name, f.is_own AS is_own_farm, g.variety,
               g.process, g.harvest_year, g.sca_score, g.moisture_pct, g.min_stock_kg, g.location,
               g.stock_kg, g.avg_cost_per_kg, g.is_active
        FROM green_coffees g
        JOIN farms f ON f.id = g.farm_id
        WHERE (%(include_inactive)s OR g.is_active)
          AND (%(search)s = '' OR g.code ILIKE %(pattern)s OR g.name ILIKE %(pattern)s
               OR g.variety ILIKE %(pattern)s OR f.name ILIKE %(pattern)s)
        ORDER BY g.name, g.harvest_year DESC
        """,
        list_filters(search, include_inactive),
    ).fetchall()


def list_green_coffee_options(connection: Connection, include_id: int | None = None) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, code, name, harvest_year FROM green_coffees
        WHERE is_active OR id = %s
        ORDER BY name, harvest_year DESC
        """,
        (include_id,),
    ).fetchall()


def find_green_coffee_code(connection: Connection, green_coffee_id: int) -> str | None:
    row = connection.execute("SELECT code FROM green_coffees WHERE id = %s", (green_coffee_id,)).fetchone()
    return row["code"] if row else None


def list_packaging_items(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, kind, capacity_g, min_stock, location, stock, avg_unit_cost, is_active
        FROM packaging_items
        WHERE (%(include_inactive)s OR is_active)
          AND (%(search)s = '' OR name ILIKE %(pattern)s OR location ILIKE %(pattern)s)
        ORDER BY kind, capacity_g NULLS FIRST, name
        """,
        list_filters(search, include_inactive),
    ).fetchall()


def list_packaging_options(
    connection: Connection, kind: PackagingKind, include_id: int | None = None
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT id, name, capacity_g FROM packaging_items
        WHERE kind = %s AND (is_active OR id = %s)
        ORDER BY capacity_g NULLS FIRST, name
        """,
        (kind.value, include_id),
    ).fetchall()


def find_packaging_spec(connection: Connection, packaging_item_id: int) -> PackagingSpec | None:
    row = connection.execute(
        "SELECT name, kind, capacity_g FROM packaging_items WHERE id = %s",
        (packaging_item_id,),
    ).fetchone()
    return PackagingSpec(row["name"], PackagingKind(row["kind"]), row["capacity_g"]) if row else None


def count_products_using_packaging(connection: Connection, packaging_item_id: int) -> int:
    row = connection.execute(
        "SELECT count(*) AS total FROM products WHERE bag_id = %(id)s OR label_id = %(id)s",
        {"id": packaging_item_id},
    ).fetchone()
    return row["total"]


def list_products(connection: Connection, search: str, include_inactive: bool) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT p.id, p.sku, p.name, p.green_coffee_id, g.code AS green_coffee_code, g.name AS green_coffee_name,
               p.roast_profile, p.grind, p.weight_g, p.bag_id, p.label_id, p.price_local, p.price_online,
               p.price_wholesale, p.min_stock, p.location, p.stock, p.avg_unit_cost, p.is_active
        FROM products p
        JOIN green_coffees g ON g.id = p.green_coffee_id
        WHERE (%(include_inactive)s OR p.is_active)
          AND (%(search)s = '' OR p.sku ILIKE %(pattern)s OR p.name ILIKE %(pattern)s
               OR g.name ILIKE %(pattern)s)
        ORDER BY p.name, p.weight_g
        """,
        list_filters(search, include_inactive),
    ).fetchall()
