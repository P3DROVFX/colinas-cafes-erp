from decimal import Decimal

import pytest

from core.errors import BusinessRuleError
from domain.brazil import PersonType
from domain.partners import CustomerInput, Segment, SupplierInput, SupplyType, validate_customer, validate_supplier


def make_supplier(**changes) -> SupplierInput:
    values = {
        "name": "  Sítio   Boa Vista ",
        "person_type": PersonType.INDIVIDUAL,
        "document": "529.982.247-25",
        "supply_type": SupplyType.GREEN_COFFEE,
        "email": "Contato@BoaVista.com.br",
        "state": "pe",
    }
    return SupplierInput(**(values | changes))


def make_customer(**changes) -> CustomerInput:
    values = {"name": "Café do Largo", "person_type": PersonType.COMPANY, "segment": Segment.COFFEE_SHOP,
              "document": "11.222.333/0001-81"}  # fmt: skip
    return CustomerInput(**(values | changes))


def test_supplier_is_normalized():
    supplier = validate_supplier(make_supplier())
    assert supplier.name == "Sítio Boa Vista"
    assert supplier.document == "52998224725"
    assert supplier.email == "contato@boavista.com.br"
    assert supplier.state == "PE"


@pytest.mark.parametrize(
    "changes",
    [
        {"document": "529.982.247-24"},
        {"document": ""},
        {"person_type": PersonType.COMPANY},
        {"email": "sem-arroba"},
        {"state": "XX"},
        {"name": "   "},
        {"lead_time_days": -1},
    ],
)
def test_invalid_supplier_is_rejected(changes):
    with pytest.raises(BusinessRuleError):
        validate_supplier(make_supplier(**changes))


def test_individual_consumer_may_skip_document():
    customer = validate_customer(
        make_customer(person_type=PersonType.INDIVIDUAL, segment=Segment.CONSUMER, document=None)
    )
    assert customer.document is None


def test_business_segment_requires_company():
    with pytest.raises(BusinessRuleError, match="pessoa física"):
        validate_customer(make_customer(person_type=PersonType.INDIVIDUAL, document="529.982.247-25"))


def test_company_customer_requires_cnpj():
    with pytest.raises(BusinessRuleError, match="CNPJ"):
        validate_customer(make_customer(document=None))


@pytest.mark.parametrize("changes", [{"payment_term_days": 91}, {"credit_limit": Decimal("-1")}])
def test_customer_credit_terms_are_bounded(changes):
    with pytest.raises(BusinessRuleError):
        validate_customer(make_customer(**changes))
