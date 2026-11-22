import pytest

from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from domain.brazil import PersonType
from domain.partners import CustomerInput, Segment, SupplierInput, SupplyType
from services import partners as partners_service

SUPPLIER = SupplierInput("Sítio Boa Vista", PersonType.INDIVIDUAL, "529.982.247-25", SupplyType.GREEN_COFFEE)
CUSTOMER = CustomerInput("Café do Largo", PersonType.COMPANY, Segment.COFFEE_SHOP, "11.222.333/0001-81")


def test_duplicate_supplier_document_is_a_business_error(make_user):
    finance = make_user(Role.FINANCE)
    partners_service.create_supplier(finance, SUPPLIER)
    with pytest.raises(BusinessRuleError, match="Já existe um fornecedor"):
        partners_service.create_supplier(finance, SUPPLIER)


def test_supplier_search_matches_formatted_document(make_user):
    finance = make_user(Role.FINANCE)
    partners_service.create_supplier(finance, SUPPLIER)
    assert len(partners_service.list_suppliers(finance, "529.982")) == 1


def test_sales_manages_customers_but_not_suppliers(make_user):
    sales = make_user(Role.SALES)
    customer_id = partners_service.create_customer(sales, CUSTOMER)
    partners_service.delete_customer(sales, customer_id)
    with pytest.raises(AccessDeniedError):
        partners_service.create_supplier(sales, SUPPLIER)


def test_walk_in_customer_is_protected(make_user):
    manager = make_user(Role.MANAGER)
    [walk_in] = partners_service.list_customers(manager, "Consumidor Final")
    assert walk_in["is_system"]
    with pytest.raises(BusinessRuleError, match="integrações"):
        partners_service.delete_customer(manager, walk_in["id"])
    with pytest.raises(BusinessRuleError, match="integrações"):
        partners_service.set_customer_active(manager, walk_in["id"], False)


def test_inactive_customers_are_hidden_by_default(make_user):
    manager = make_user(Role.MANAGER)
    customer_id = partners_service.create_customer(manager, CUSTOMER)
    partners_service.set_customer_active(manager, customer_id, False)
    assert customer_id not in [row["id"] for row in partners_service.list_customers(manager)]
    assert customer_id in [row["id"] for row in partners_service.list_customers(manager, include_inactive=True)]
