from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.numbers import format_decimal


class SettingType(StrEnum):
    INT = "INT"
    DECIMAL = "DECIMAL"
    TEXT = "TEXT"
    BOOL = "BOOL"
    DATE = "DATE"


@dataclass(frozen=True, slots=True)
class SettingRule:
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    optional: bool = False


SETTING_RULES: dict[str, SettingRule] = {
    "roaster_capacity_kg": SettingRule(Decimal("1"), Decimal("100")),
    "roast_min_kg": SettingRule(Decimal("0.1"), Decimal("100")),
    "weight_loss_warn_min_pct": SettingRule(Decimal("0"), Decimal("50")),
    "weight_loss_warn_max_pct": SettingRule(Decimal("0"), Decimal("50")),
    "weight_loss_block_min_pct": SettingRule(Decimal("0"), Decimal("50")),
    "weight_loss_block_max_pct": SettingRule(Decimal("0"), Decimal("60")),
    "roast_batch_alert_days": SettingRule(Decimal("1"), Decimal("90")),
    "product_shelf_life_months": SettingRule(Decimal("1"), Decimal("36")),
    "default_shipping_box_id": SettingRule(optional=True),
    "quote_validity_days": SettingRule(Decimal("1"), Decimal("60")),
    "max_discount_pct": SettingRule(Decimal("0"), Decimal("100")),
    "wholesale_min_order_kg": SettingRule(Decimal("0"), Decimal("1000")),
    "wholesale_default_term_days": SettingRule(Decimal("0"), Decimal("90")),
    "overdue_tolerance_days": SettingRule(Decimal("0"), Decimal("90")),
    "credit_card_fee_pct": SettingRule(Decimal("0"), Decimal("20")),
    "credit_card_term_days": SettingRule(Decimal("0"), Decimal("60")),
    "debit_card_fee_pct": SettingRule(Decimal("0"), Decimal("20")),
    "debit_card_term_days": SettingRule(Decimal("0"), Decimal("30")),
    "due_alert_days": SettingRule(Decimal("1"), Decimal("60")),
    "packaging_lead_time_days": SettingRule(Decimal("0"), Decimal("120")),
    "safety_stock_days": SettingRule(Decimal("0"), Decimal("120")),
    "operation_start_date": SettingRule(),
}

ORDERED_PAIRS = (
    ("roast_min_kg", "roaster_capacity_kg", "O mínimo por torra deve ser menor que a capacidade do torrador."),
    ("weight_loss_block_min_pct", "weight_loss_warn_min_pct", "A quebra mínima bloqueada fica abaixo do alerta."),
    ("weight_loss_warn_min_pct", "weight_loss_warn_max_pct", "O alerta mínimo de quebra fica abaixo do máximo."),
    ("weight_loss_warn_max_pct", "weight_loss_block_max_pct", "A quebra máxima bloqueada fica acima do alerta."),
)  # fmt: skip


def normalize_setting(key: str, value_type: SettingType, raw: str | None, description: str) -> str | None:
    """Checks one parameter against its type and range and returns it in canonical text form."""
    rule = SETTING_RULES.get(key, SettingRule())
    text = (raw or "").strip().replace(",", ".")
    if not text:
        if rule.optional:
            return None
        raise BusinessRuleError(f"Informe um valor para “{description}”.")
    if value_type is SettingType.DATE:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as error:
            raise BusinessRuleError(f"“{description}” precisa de uma data válida.") from error
    if value_type in (SettingType.TEXT, SettingType.BOOL):
        return text
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise BusinessRuleError(f"“{description}” precisa de um número.") from error
    if value_type is SettingType.INT and number != number.to_integral_value():
        raise BusinessRuleError(f"“{description}” precisa de um número inteiro.")
    if (rule.minimum is not None and number < rule.minimum) or (rule.maximum is not None and number > rule.maximum):
        raise BusinessRuleError(
            f"“{description}” deve ficar entre {format_decimal(rule.minimum, 1)} e {format_decimal(rule.maximum, 1)}."
        )
    return str(int(number)) if value_type is SettingType.INT else format(number.normalize(), "f")


def ensure_consistent_settings(values: dict[str, str | None]) -> None:
    for lower, upper, message in ORDERED_PAIRS:
        if values.get(lower) and values.get(upper) and Decimal(values[lower]) >= Decimal(values[upper]):
            raise BusinessRuleError(message)
