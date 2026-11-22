from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.brazil import PersonType
from domain.fields import (
    clean_document,
    clean_email,
    clean_state,
    clean_text,
    ensure_between,
    ensure_not_negative,
    require_text,
)

MAX_PAYMENT_TERM_DAYS = 90


class SupplyType(StrEnum):
    GREEN_COFFEE = "GREEN_COFFEE"
    PACKAGING = "PACKAGING"
    SERVICE = "SERVICE"


class Segment(StrEnum):
    CONSUMER = "CONSUMER"
    COFFEE_SHOP = "COFFEE_SHOP"
    RESTAURANT = "RESTAURANT"
    EMPORIUM = "EMPORIUM"
    COMPANY = "COMPANY"


@dataclass(frozen=True, slots=True)
class SupplierInput:
    name: str
    person_type: PersonType
    document: str | None
    supply_type: SupplyType
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    state: str | None = None
    lead_time_days: int = 7


@dataclass(frozen=True, slots=True)
class CustomerInput:
    name: str
    person_type: PersonType
    segment: Segment
    document: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    payment_term_days: int = 0
    credit_limit: Decimal = Decimal("0")


def validate_supplier(data: SupplierInput) -> SupplierInput:
    ensure_not_negative(data.lead_time_days, "O prazo de entrega não pode ser negativo.")
    return replace(
        data,
        name=require_text(data.name, "Informe o nome ou a razão social do fornecedor."),
        document=clean_document(data.person_type, data.document, required=True),
        email=clean_email(data.email),
        phone=clean_text(data.phone),
        city=clean_text(data.city),
        state=clean_state(data.state),
    )


def validate_customer(data: CustomerInput) -> CustomerInput:
    is_company = data.person_type is PersonType.COMPANY
    if data.segment is not Segment.CONSUMER and not is_company:
        raise BusinessRuleError("Somente clientes do segmento Consumidor podem ser pessoa física. Use o CNPJ.")
    ensure_between(
        data.payment_term_days,
        0,
        MAX_PAYMENT_TERM_DAYS,
        f"O prazo de pagamento deve ficar entre 0 e {MAX_PAYMENT_TERM_DAYS} dias.",
    )
    ensure_not_negative(data.credit_limit, "O limite de crédito não pode ser negativo.")
    return replace(
        data,
        name=require_text(data.name, "Informe o nome ou a razão social do cliente."),
        document=clean_document(data.person_type, data.document, required=is_company),
        email=clean_email(data.email),
        phone=clean_text(data.phone),
        address=clean_text(data.address),
        city=clean_text(data.city),
        state=clean_state(data.state),
    )
