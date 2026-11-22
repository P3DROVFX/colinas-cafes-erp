from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

from psycopg import Connection
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from core.db import transaction
from core.errors import BusinessRuleError
from domain.access import Permission, User, ensure_permission
from repositories import records
from repositories.records import MasterTable

SYSTEM_RECORD_MESSAGE = "Este cadastro é usado pelas integrações do sistema e não pode ser excluído nem inativado."


class RecordInUseError(BusinessRuleError):
    pass


@contextmanager
def duplicate_guard(message: str) -> Iterator[None]:
    try:
        yield
    except UniqueViolation as error:
        raise BusinessRuleError(message) from error


def record_values(data: object) -> dict[str, Any]:
    return asdict(data)


def load_record(connection: Connection, table: MasterTable, record_id: int) -> dict[str, Any]:
    record = records.find_record_for_update(connection, table, record_id)
    if record is None:
        raise BusinessRuleError("Cadastro não encontrado. Atualize a página e tente de novo.")
    return record


def ensure_unchanged(record: dict[str, Any], values: dict[str, Any], columns: tuple[str, ...], message: str) -> None:
    if any(record[column] != values[column] for column in columns):
        raise BusinessRuleError(message)


def delete_master_record(
    actor: User,
    permission: Permission,
    table: MasterTable,
    record_id: int,
    in_use_message: str,
    ensure_deletable: Callable[[Connection, dict[str, Any]], None] | None = None,
) -> None:
    ensure_permission(actor, permission)
    try:
        with transaction(actor.email) as connection:
            record = load_record(connection, table, record_id)
            if record.get("is_system"):
                raise BusinessRuleError(SYSTEM_RECORD_MESSAGE)
            if ensure_deletable is not None:
                ensure_deletable(connection, record)
            records.delete_record(connection, table, record_id)
    except ForeignKeyViolation as error:
        raise RecordInUseError(in_use_message) from error


def set_master_record_active(
    actor: User,
    permission: Permission,
    table: MasterTable,
    record_id: int,
    is_active: bool,
) -> None:
    ensure_permission(actor, permission)
    with transaction(actor.email) as connection:
        record = load_record(connection, table, record_id)
        if record.get("is_system") and not is_active:
            raise BusinessRuleError(SYSTEM_RECORD_MESSAGE)
        records.set_record_active(connection, table, record_id, is_active)
