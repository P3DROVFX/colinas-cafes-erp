from dataclasses import dataclass
from datetime import date
from typing import Any

from core.clock import today
from core.db import transaction
from core.errors import BusinessRuleError
from domain.access import Permission, User, ensure_permission
from domain.finance import EntryDisplayStatus, EntryType
from repositories import finance as finance_repository


@dataclass(frozen=True, slots=True)
class EntryFilters:
    due_from: date
    due_to: date
    entry_type: EntryType | None
    statuses: tuple[EntryDisplayStatus, ...]


def list_entries(actor: User, filters: EntryFilters) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_FINANCE)
    if filters.due_from > filters.due_to:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")
    with transaction(actor.email) as connection:
        return finance_repository.list_entries(
            connection,
            today(),
            filters.due_from,
            filters.due_to,
            filters.entry_type.value if filters.entry_type else None,
            [status.value for status in filters.statuses],
        )
