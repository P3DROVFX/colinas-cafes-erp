import re
from enum import StrEnum

STATES: tuple[str, ...] = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)  # fmt: skip

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PersonType(StrEnum):
    INDIVIDUAL = "PF"
    COMPANY = "PJ"


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _check_digit(digits: str, weights: range | list[int]) -> int:
    remainder = sum(int(digit) * weight for digit, weight in zip(digits, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cpf(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    first = _check_digit(digits[:9], range(10, 1, -1))
    second = _check_digit(digits[:10], range(11, 1, -1))
    return digits[9:] == f"{first}{second}"


def is_valid_cnpj(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    first_weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    first = _check_digit(digits[:12], first_weights)
    second = _check_digit(digits[:13], [6, *first_weights])
    return digits[12:] == f"{first}{second}"


def is_valid_document(person_type: PersonType, value: str) -> bool:
    if person_type is PersonType.INDIVIDUAL:
        return is_valid_cpf(value)
    return is_valid_cnpj(value)


def document_name(person_type: PersonType) -> str:
    return "CPF" if person_type is PersonType.INDIVIDUAL else "CNPJ"


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match(value))
