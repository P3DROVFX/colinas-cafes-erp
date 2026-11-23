from datetime import date

import pytest

from core.errors import AccessDeniedError, BusinessRuleError
from domain.dates import resolve_business_date

TODAY = date(2026, 11, 22)


def test_missing_date_means_today():
    assert resolve_business_date(None, TODAY, can_backdate=False) == TODAY


def test_only_admin_can_backdate():
    with pytest.raises(AccessDeniedError):
        resolve_business_date(date(2026, 11, 1), TODAY, can_backdate=False)
    assert resolve_business_date(date(2026, 11, 1), TODAY, can_backdate=True) == date(2026, 11, 1)


@pytest.mark.parametrize("requested", [date(2026, 11, 23), date(2025, 11, 1)])
def test_future_and_too_old_dates_are_rejected(requested):
    with pytest.raises(BusinessRuleError):
        resolve_business_date(requested, TODAY, can_backdate=True)
