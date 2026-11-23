from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from domain.finance import EntryType
from domain.inventory import StockItemKind


@dataclass(frozen=True, slots=True)
class StockChange:
    kind: StockItemKind
    label: str
    before: Decimal
    after: Decimal
    unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class EntryChange:
    entry_id: int
    entry_type: EntryType
    description: str
    amount: Decimal
    due_date: date
    action: str = "created"


@dataclass(slots=True)
class OperationEffects:
    stock: list[StockChange] = field(default_factory=list)
    entries: list[EntryChange] = field(default_factory=list)
