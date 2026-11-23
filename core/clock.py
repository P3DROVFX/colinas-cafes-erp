from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from zoneinfo import ZoneInfo

TIMEZONE_NAME = "America/Recife"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

_simulated_day: ContextVar[date | None] = ContextVar("simulated_day", default=None)


def today() -> date:
    return _simulated_day.get() or datetime.now(TIMEZONE).date()


@contextmanager
def business_day(day: date) -> Iterator[None]:
    """Runs operations as if it were that day. Only the history seed uses it; the app always runs on the real date."""
    token = _simulated_day.set(day)
    try:
        yield
    finally:
        _simulated_day.reset(token)
