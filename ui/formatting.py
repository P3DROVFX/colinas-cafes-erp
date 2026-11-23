from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

import pandas as pd
from pandas.io.formats.style import Styler

from domain.brazil import only_digits
from domain.numbers import format_decimal


def format_datetime(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else "—"


def format_currency(value: Decimal | float | int) -> str:
    formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def format_signed_currency(value: Decimal) -> str:
    """Leading sign so metric deltas show the right direction."""
    return f"{'-' if value < 0 else '+'}{format_currency(abs(value))}"


def format_unit_cost(value: Decimal) -> str:
    """Unit costs keep four decimals only when the cents alone would hide part of the value."""
    places = 2 if value == round(value, 2) else 4
    return f"R$ {format_decimal(value, places)}"


def format_document(value: str | None) -> str:
    digits = only_digits(value or "")
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return value or ""


def format_place(city: str | None, state: str | None) -> str:
    return " / ".join(part for part in (city, state) if part)


def to_float(value: Decimal | int | None) -> float | None:
    return None if value is None else float(value)


def style_numbers(frame: pd.DataFrame, decimal_places: Mapping[str, int]) -> Styler:
    styler = frame.style
    for column, places in decimal_places.items():
        styler = styler.format(precision=places, decimal=",", thousands=".", na_rep="—", subset=[column])
    return styler
