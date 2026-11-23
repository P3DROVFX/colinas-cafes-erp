from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from psycopg import Connection

from core.db import transaction
from domain.access import Permission, User, ensure_permission
from domain.inventory import StockItemKind
from repositories import integrity as integrity_repository


@dataclass(frozen=True, slots=True)
class IntegrityCheck:
    code: str
    title: str
    run: Callable[[Connection], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class IntegrityResult:
    code: str
    title: str
    divergences: list[dict[str, Any]]

    @property
    def passed(self) -> bool:
        return not self.divergences


def _for_every_stock_kind(
    query: Callable[[Connection, StockItemKind], list[dict[str, Any]]],
) -> Callable[[Connection], list[dict[str, Any]]]:
    def run(connection: Connection) -> list[dict[str, Any]]:
        return [row for kind in StockItemKind for row in query(connection, kind)]

    return run


CHECKS: tuple[IntegrityCheck, ...] = (
    IntegrityCheck(
        "I1",
        "Saldo de cada item é igual à soma dos movimentos",
        _for_every_stock_kind(integrity_repository.stock_differs_from_movements),
    ),
    IntegrityCheck(
        "I2",
        "Saldo após o último movimento é igual ao saldo atual",
        _for_every_stock_kind(integrity_repository.last_balance_differs_from_stock),
    ),
    IntegrityCheck(
        "I3",
        "Vendas faturadas têm título a receber não cancelado com o valor total",
        integrity_repository.invoiced_sales_without_matching_receivable,
    ),
    IntegrityCheck(
        "I4",
        "Baixa de estoque de cada venda é igual à soma dos itens",
        integrity_repository.sales_with_wrong_stock_out,
    ),
    IntegrityCheck(
        "I5",
        "Compras recebidas têm títulos a pagar com o valor e o número de parcelas corretos",
        integrity_repository.received_purchases_with_wrong_payables,
    ),
    IntegrityCheck(
        "I6",
        "Itens de vendas faturadas têm o custo registrado no momento da venda",
        integrity_repository.invoiced_items_without_cost_snapshot,
    ),
    IntegrityCheck(
        "I7",
        "Lotes torrados encerrados estão zerados e lotes zerados estão encerrados",
        integrity_repository.roast_batches_with_inconsistent_status,
    ),
    IntegrityCheck(
        "I8",
        "Todo título gerado por uma operação aponta para um documento existente",
        integrity_repository.entries_without_source_document,
    ),
    IntegrityCheck(
        "I9",
        "Valor das entradas de envase no estoque é igual ao valor dos lotes de envase",
        integrity_repository.packing_value_differs_from_batches,
    ),
)


def run_integrity_checks(actor: User) -> list[IntegrityResult]:
    ensure_permission(actor, Permission.VIEW_INTEGRITY)
    with transaction(actor.email) as connection:
        return [IntegrityResult(check.code, check.title, check.run(connection)) for check in CHECKS]
