from decimal import Decimal, InvalidOperation

from psycopg import Connection

from core.errors import ConfigurationError
from repositories.settings import find_setting_values


def decimal_settings(connection: Connection, keys: list[str]) -> dict[str, Decimal]:
    values = find_setting_values(connection, keys)
    try:
        return {key: Decimal(values[key]) for key in keys}
    except (KeyError, TypeError, InvalidOperation) as error:
        raise ConfigurationError("Parâmetros do sistema ausentes ou inválidos. Revise os parâmetros.") from error


def int_setting(connection: Connection, key: str) -> int:
    return int(decimal_settings(connection, [key])[key])


def optional_int_setting(connection: Connection, key: str) -> int | None:
    value = find_setting_values(connection, [key]).get(key)
    return int(value) if value else None
