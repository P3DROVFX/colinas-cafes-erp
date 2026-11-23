from datetime import date, datetime
from zoneinfo import ZoneInfo

TIMEZONE_NAME = "America/Recife"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)


def today() -> date:
    return datetime.now(TIMEZONE).date()
