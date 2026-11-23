from decimal import ROUND_HALF_UP, Decimal

MONEY = Decimal("0.01")
UNIT_COST = Decimal("0.0001")
KILOGRAMS = Decimal("0.001")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def round_unit_cost(value: Decimal) -> Decimal:
    return value.quantize(UNIT_COST, rounding=ROUND_HALF_UP)


def round_kilograms(value: Decimal) -> Decimal:
    return value.quantize(KILOGRAMS, rounding=ROUND_HALF_UP)


def format_decimal(value: Decimal, places: int) -> str:
    formatted = f"{value:,.{places}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")
