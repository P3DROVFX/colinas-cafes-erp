from typing import Any

from core.db import transaction
from domain.access import Permission, User, ensure_permission
from domain.partners import CustomerInput, SupplierInput, SupplyType, validate_customer, validate_supplier
from repositories import partners as partners_repository
from repositories import records
from repositories.records import MasterTable
from services.master_data import (
    delete_master_record,
    duplicate_guard,
    load_record,
    record_values,
    set_master_record_active,
)

DUPLICATE_SUPPLIER_MESSAGE = "Já existe um fornecedor com este CPF/CNPJ."
DUPLICATE_CUSTOMER_MESSAGE = "Já existe um cliente com este CPF/CNPJ."


def list_suppliers(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return partners_repository.list_suppliers(connection, search, include_inactive)


def list_supplier_options(actor: User, supply_type: SupplyType, include_id: int | None = None) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return partners_repository.list_supplier_options(connection, supply_type, include_id)


def create_supplier(actor: User, data: SupplierInput) -> int:
    ensure_permission(actor, Permission.MANAGE_SUPPLIERS)
    data = validate_supplier(data)
    with duplicate_guard(DUPLICATE_SUPPLIER_MESSAGE), transaction(actor.email) as connection:
        return records.insert_record(connection, MasterTable.SUPPLIERS, record_values(data))


def update_supplier(actor: User, supplier_id: int, data: SupplierInput) -> None:
    ensure_permission(actor, Permission.MANAGE_SUPPLIERS)
    data = validate_supplier(data)
    with duplicate_guard(DUPLICATE_SUPPLIER_MESSAGE), transaction(actor.email) as connection:
        load_record(connection, MasterTable.SUPPLIERS, supplier_id)
        records.update_record(connection, MasterTable.SUPPLIERS, supplier_id, record_values(data))


def delete_supplier(actor: User, supplier_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_SUPPLIERS,
        MasterTable.SUPPLIERS,
        supplier_id,
        "Este fornecedor já tem fazendas, compras ou títulos. Inative-o para tirá-lo das novas operações.",
    )


def set_supplier_active(actor: User, supplier_id: int, is_active: bool) -> None:
    set_master_record_active(actor, Permission.MANAGE_SUPPLIERS, MasterTable.SUPPLIERS, supplier_id, is_active)


def list_customers(actor: User, search: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    with transaction(actor.email) as connection:
        return partners_repository.list_customers(connection, search, include_inactive)


def create_customer(actor: User, data: CustomerInput) -> int:
    ensure_permission(actor, Permission.MANAGE_CUSTOMERS)
    data = validate_customer(data)
    with duplicate_guard(DUPLICATE_CUSTOMER_MESSAGE), transaction(actor.email) as connection:
        return records.insert_record(connection, MasterTable.CUSTOMERS, record_values(data))


def update_customer(actor: User, customer_id: int, data: CustomerInput) -> None:
    ensure_permission(actor, Permission.MANAGE_CUSTOMERS)
    data = validate_customer(data)
    with duplicate_guard(DUPLICATE_CUSTOMER_MESSAGE), transaction(actor.email) as connection:
        load_record(connection, MasterTable.CUSTOMERS, customer_id)
        records.update_record(connection, MasterTable.CUSTOMERS, customer_id, record_values(data))


def delete_customer(actor: User, customer_id: int) -> None:
    delete_master_record(
        actor,
        Permission.MANAGE_CUSTOMERS,
        MasterTable.CUSTOMERS,
        customer_id,
        "Este cliente já tem vendas ou títulos. Inative-o para tirá-lo das novas vendas.",
    )


def set_customer_active(actor: User, customer_id: int, is_active: bool) -> None:
    set_master_record_active(actor, Permission.MANAGE_CUSTOMERS, MasterTable.CUSTOMERS, customer_id, is_active)
