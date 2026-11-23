from datetime import date

from core.clock import business_day, today


def test_business_day_overrides_today_only_inside_the_block():
    real_today = today()
    with business_day(date(2026, 6, 1)):
        assert today() == date(2026, 6, 1)
    assert today() == real_today
