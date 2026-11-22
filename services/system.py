from dataclasses import dataclass
from datetime import datetime

from core.db import fetch_one


@dataclass(frozen=True, slots=True)
class SystemStatus:
    database_time: datetime
    schema_version: str | None


def get_system_status() -> SystemStatus:
    row = fetch_one(
        """
        SELECT now() AS database_time,
               (SELECT max(version) FROM schema_migrations) AS schema_version
        """
    )
    return SystemStatus(database_time=row["database_time"], schema_version=row["schema_version"])
