from decimal import Decimal

from core.errors import BusinessRuleError
from domain.brazil import STATES, PersonType, document_name, is_valid_document, is_valid_email, only_digits


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = " ".join(value.split())
    return stripped or None


def require_text(value: str | None, message: str) -> str:
    cleaned = clean_text(value)
    if cleaned is None:
        raise BusinessRuleError(message)
    return cleaned


def clean_state(value: str | None, required: bool = False) -> str | None:
    state = clean_text(value)
    if state is None:
        if required:
            raise BusinessRuleError("Informe a UF.")
        return None
    state = state.upper()
    if state not in STATES:
        raise BusinessRuleError(f"UF inválida: {state}.")
    return state


def clean_email(value: str | None) -> str | None:
    email = clean_text(value)
    if email is None:
        return None
    email = email.lower()
    if not is_valid_email(email):
        raise BusinessRuleError(f"E-mail inválido: {email}.")
    return email


def clean_document(person_type: PersonType, value: str | None, required: bool) -> str | None:
    label = document_name(person_type)
    digits = only_digits(value or "")
    if not digits:
        if required:
            raise BusinessRuleError(f"Informe o {label}.")
        return None
    if not is_valid_document(person_type, digits):
        raise BusinessRuleError(f"{label} inválido: confira os dígitos.")
    return digits


def ensure_between(value: int | Decimal | None, minimum: int | Decimal, maximum: int | Decimal, message: str) -> None:
    if value is not None and not minimum <= value <= maximum:
        raise BusinessRuleError(message)


def ensure_not_negative(value: int | Decimal, message: str) -> None:
    if value < 0:
        raise BusinessRuleError(message)


def ensure_positive(value: int | Decimal | None, message: str) -> None:
    if value is None or value <= 0:
        raise BusinessRuleError(message)
