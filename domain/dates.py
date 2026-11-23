import calendar
from datetime import date

from core.errors import AccessDeniedError, BusinessRuleError

MAX_BACKDATE_DAYS = 365


def resolve_business_date(requested: date | None, today: date, can_backdate: bool) -> date:
    if requested is None or requested == today:
        return today
    if requested > today:
        raise BusinessRuleError("A data da operação não pode estar no futuro.")
    if not can_backdate:
        raise AccessDeniedError("Somente o administrador registra operações com data retroativa.")
    if (today - requested).days > MAX_BACKDATE_DAYS:
        raise BusinessRuleError(f"A data retroativa pode voltar no máximo {MAX_BACKDATE_DAYS} dias.")
    return requested


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))
