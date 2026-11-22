from typing import Any

from psycopg import Connection

from core.db import transaction
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Permission, User, ensure_permission, has_permission
from domain.catalog import (
    FarmInput,
    GreenCoffeeInput,
    PackagingItemInput,
    PackagingKind,
    PackagingSpec,
    ProductInput,
    build_sku,
    validate_farm,
    validate_green_coffee,
    validate_packaging_item,
    validate_product,
)
from domain.partners import SupplyType
from repositories import catalog as catalog_repository
from repositories import partners as partners_repository
from repositories import records
from repositories.records import MasterTable
from repositories.settings import find_setting_value
from services.master_data import (
    delete_master_record,
    duplicate_guard,
    ensure_unchanged,
    load_record,
    record_values,
    set_master_record_active,
)

GREEN_COFFEE_IDENTITY = ("code", "farm_id", "variety", "process", "harvest_year")
PRODUCT_IDENTITY = ("green_coffee_id", "roast_profile", "grind", "weight_g")
PRODUCT_PRICES = ("price_local", "price_online", "price_wholesale")
PACKAGING_SHAPE = ("kind", "capacity_g")

DUPLICATE_FARM_MESSAGE = "Já existe uma fazenda com este nome."
DUPLICATE_GREEN_COFFEE_MESSAGE = (
    "Já existe um café verde com este código ou com a mesma fazenda, varietal, processo e safra."
)
DUPLICATE_PACKAGING_MESSAGE = "Já existe uma embalagem com este nome."
DUPLICATE_PRODUCT_MESSAGE = "Já existe um produto com este café, perfil de torra, moagem e peso."


def list_farms(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_farms(connection, search, include_inactive)


def list_farm_options(actor: User, include_id: int | None = None) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_farm_options(connection, include_id)


def _ensure_green_coffee_supplier(connection: Connection, supplier_id: int | None) -> None:
    if supplier_id is None:
        return
    if partners_repository.find_supplier_supply_type(connection, supplier_id) is not SupplyType.GREEN_COFFEE:
        raise BusinessRuleError("O fornecedor de uma fazenda parceira precisa ser um fornecedor de café verde.")


def create_farm(actor: User, data: FarmInput) -> int:
    ensure_permission(actor, Permission.MANAGE_CATALOG)
    data = validate_farm(data)
    with duplicate_guard(DUPLICATE_FARM_MESSAGE), transaction(actor.email) as connection:
        _ensure_green_coffee_supplier(connection, data.supplier_id)
        return records.insert_record(connection, MasterTable.FARMS, record_values(data))


def update_farm(actor: User, farm_id: int, data: FarmInput) -> None:
    ensure_permission(actor, Permission.MANAGE_CATALOG)
    data = validate_farm(data)
    values = record_values(data)
    with duplicate_guard(DUPLICATE_FARM_MESSAGE), transaction(actor.email) as connection:
        farm = load_record(connection, MasterTable.FARMS, farm_id)
        ensure_unchanged(
            farm,
            values,
            ("is_own",),
            "Não é possível trocar uma fazenda entre própria e parceira. Cadastre outra fazenda.",
        )
        _ensure_green_coffee_supplier(connection, data.supplier_id)
        records.update_record(connection, MasterTable.FARMS, farm_id, values)


def delete_farm(actor: User, farm_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_CATALOG,
        MasterTable.FARMS,
        farm_id,
        "Esta fazenda já tem cafés verdes cadastrados. Inative-a para tirá-la das novas operações.",
    )


def set_farm_active(actor: User, farm_id: int, is_active: bool) -> None:
    set_master_record_active(actor, Permission.MANAGE_CATALOG, MasterTable.FARMS, farm_id, is_active)


def list_green_coffees(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_green_coffees(connection, search, include_inactive)


def list_green_coffee_options(actor: User, include_id: int | None = None) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_green_coffee_options(connection, include_id)


def create_green_coffee(actor: User, data: GreenCoffeeInput) -> int:
    ensure_permission(actor, Permission.MANAGE_CATALOG)
    data = validate_green_coffee(data)
    with duplicate_guard(DUPLICATE_GREEN_COFFEE_MESSAGE), transaction(actor.email) as connection:
        return records.insert_record(connection, MasterTable.GREEN_COFFEES, record_values(data))


def update_green_coffee(actor: User, green_coffee_id: int, data: GreenCoffeeInput) -> None:
    ensure_permission(actor, Permission.MANAGE_CATALOG)
    data = validate_green_coffee(data)
    values = record_values(data)
    with duplicate_guard(DUPLICATE_GREEN_COFFEE_MESSAGE), transaction(actor.email) as connection:
        coffee = load_record(connection, MasterTable.GREEN_COFFEES, green_coffee_id)
        ensure_unchanged(
            coffee,
            values,
            GREEN_COFFEE_IDENTITY,
            "Código, fazenda, varietal, processo e safra identificam o lote e não podem mudar. Cadastre outro café.",
        )
        records.update_record(connection, MasterTable.GREEN_COFFEES, green_coffee_id, values)


def delete_green_coffee(actor: User, green_coffee_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_CATALOG,
        MasterTable.GREEN_COFFEES,
        green_coffee_id,
        "Este café já tem produtos, compras ou movimentos de estoque. Inative-o para tirá-lo das novas operações.",
    )


def set_green_coffee_active(actor: User, green_coffee_id: int, is_active: bool) -> None:
    set_master_record_active(actor, Permission.MANAGE_CATALOG, MasterTable.GREEN_COFFEES, green_coffee_id, is_active)


def list_packaging_items(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_packaging_items(connection, search, include_inactive)


def list_packaging_options(actor: User, kind: PackagingKind, include_id: int | None = None) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_packaging_options(connection, kind, include_id)


def create_packaging_item(actor: User, data: PackagingItemInput) -> int:
    ensure_permission(actor, Permission.MANAGE_CATALOG)
    data = validate_packaging_item(data)
    with duplicate_guard(DUPLICATE_PACKAGING_MESSAGE), transaction(actor.email) as connection:
        return records.insert_record(connection, MasterTable.PACKAGING_ITEMS, record_values(data))


def update_packaging_item(actor: User, packaging_item_id: int, data: PackagingItemInput) -> None:
    ensure_permission(actor, Permission.MANAGE_CATALOG)
    data = validate_packaging_item(data)
    values = record_values(data)
    with duplicate_guard(DUPLICATE_PACKAGING_MESSAGE), transaction(actor.email) as connection:
        packaging = load_record(connection, MasterTable.PACKAGING_ITEMS, packaging_item_id)
        if catalog_repository.count_products_using_packaging(connection, packaging_item_id):
            ensure_unchanged(
                packaging,
                values,
                PACKAGING_SHAPE,
                "Esta embalagem já está em produtos, então o tipo e a capacidade não podem mudar.",
            )
        records.update_record(connection, MasterTable.PACKAGING_ITEMS, packaging_item_id, values)


def _ensure_not_default_shipping_box(connection: Connection, packaging: dict[str, Any]) -> None:
    if find_setting_value(connection, "default_shipping_box_id") == str(packaging["id"]):
        raise BusinessRuleError("Esta é a caixa de envio padrão. Escolha outra caixa padrão nos parâmetros antes.")


def delete_packaging_item(actor: User, packaging_item_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_CATALOG,
        MasterTable.PACKAGING_ITEMS,
        packaging_item_id,
        "Esta embalagem já está em produtos, compras ou movimentos. Inative-a para tirá-la das novas operações.",
        ensure_deletable=_ensure_not_default_shipping_box,
    )


def set_packaging_item_active(actor: User, packaging_item_id: int, is_active: bool) -> None:
    set_master_record_active(
        actor, Permission.MANAGE_CATALOG, MasterTable.PACKAGING_ITEMS, packaging_item_id, is_active
    )


def list_products(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return catalog_repository.list_products(connection, search, include_inactive)


def _load_packaging_spec(connection: Connection, packaging_item_id: int | None, missing_message: str) -> PackagingSpec:
    spec = catalog_repository.find_packaging_spec(connection, packaging_item_id) if packaging_item_id else None
    if spec is None:
        raise BusinessRuleError(missing_message)
    return spec


def _validate_product(connection: Connection, data: ProductInput) -> ProductInput:
    bag = _load_packaging_spec(connection, data.bag_id, "Selecione o pacote do produto.")
    label = _load_packaging_spec(connection, data.label_id, "Selecione a etiqueta do produto.")
    return validate_product(data, bag, label)


def create_product(actor: User, data: ProductInput) -> int:
    ensure_permission(actor, Permission.MANAGE_PRODUCTS)
    ensure_permission(actor, Permission.MANAGE_PRICES)
    with duplicate_guard(DUPLICATE_PRODUCT_MESSAGE), transaction(actor.email) as connection:
        data = _validate_product(connection, data)
        coffee_code = catalog_repository.find_green_coffee_code(connection, data.green_coffee_id)
        if coffee_code is None:
            raise BusinessRuleError("Café verde não encontrado.")
        sku = build_sku(coffee_code, data.roast_profile, data.grind, data.weight_g)
        return records.insert_record(connection, MasterTable.PRODUCTS, {"sku": sku, **record_values(data)})


def update_product(actor: User, product_id: int, data: ProductInput) -> None:
    ensure_permission(actor, Permission.MANAGE_PRODUCTS)
    with duplicate_guard(DUPLICATE_PRODUCT_MESSAGE), transaction(actor.email) as connection:
        data = _validate_product(connection, data)
        values = record_values(data)
        product = load_record(connection, MasterTable.PRODUCTS, product_id)
        ensure_unchanged(
            product,
            values,
            PRODUCT_IDENTITY,
            "Café, perfil de torra, moagem e peso definem o SKU e não podem mudar. Cadastre outro produto.",
        )
        prices_changed = any(product[column] != values[column] for column in PRODUCT_PRICES)
        if prices_changed and not has_permission(actor, Permission.MANAGE_PRICES):
            raise AccessDeniedError("Somente gerente ou administrador altera preços de venda.")
        records.update_record(connection, MasterTable.PRODUCTS, product_id, values)


def delete_product(actor: User, product_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_PRODUCTS,
        MasterTable.PRODUCTS,
        product_id,
        "Este produto já tem envases, vendas ou movimentos de estoque. Inative-o para tirá-lo das novas vendas.",
    )


def set_product_active(actor: User, product_id: int, is_active: bool) -> None:
    set_master_record_active(actor, Permission.MANAGE_PRODUCTS, MasterTable.PRODUCTS, product_id, is_active)
