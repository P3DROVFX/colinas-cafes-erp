from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection

from core.clock import today
from core.db import transaction
from core.errors import BusinessRuleError
from domain.access import Permission, User, ensure_permission, has_permission
from domain.catalog import RoastProfile
from domain.dates import add_months, resolve_business_date
from domain.effects import EntryChange, OperationEffects, StockChange
from domain.fields import require_text
from domain.finance import EntryType
from domain.inventory import AdjustmentReason, MovementType, SourceModule, StockBalance, StockItemKind, StockItemRef
from domain.numbers import format_decimal
from domain.partners import SupplyType
from domain.production import (
    HarvestInput,
    PackingBatchSource,
    PackingInput,
    PackingProduct,
    RoastBatchStatus,
    RoastInput,
    RoastLimits,
    can_close_batch,
    daily_code,
    daily_prefix,
    describe_shortages,
    ensure_batch_fits_product,
    find_shortages,
    harvest_unit_cost,
    packed_coffee_unit_cost,
    packing_consumed_kg,
    roasted_cost_per_kg,
    validate_harvest,
    validate_packing,
    validate_roast,
    weight_loss_pct,
)
from repositories import finance as finance_repository
from repositories import inventory as inventory_repository
from repositories import partners as partners_repository
from repositories import production as production_repository
from services.finance import require_system_category_id
from services.inventory import MovementRequest, lock_balance, record_movement
from services.parameters import decimal_settings, int_setting

HARVEST_CATEGORY = "Custos de colheita e beneficiamento"
HARVEST_MOVEMENTS = [MovementType.HARVEST_IN.value]
ROAST_MOVEMENTS = [MovementType.ROAST_OUT.value, MovementType.ROAST_IN.value]
PACKING_MOVEMENTS = [MovementType.PACKING_OUT.value, MovementType.PACKING_IN.value]
ROAST_LIMIT_SETTINGS = {
    "min_green_kg": "roast_min_kg",
    "capacity_kg": "roaster_capacity_kg",
    "warn_min_pct": "weight_loss_warn_min_pct",
    "warn_max_pct": "weight_loss_warn_max_pct",
    "block_min_pct": "weight_loss_block_min_pct",
    "block_max_pct": "weight_loss_block_max_pct",
}
SHELF_LIFE_SETTING = "product_shelf_life_months"
FRESHNESS_SETTING = "roast_batch_alert_days"


@dataclass(frozen=True, slots=True)
class HarvestResult:
    number: str
    effects: OperationEffects


@dataclass(frozen=True, slots=True)
class RoastResult:
    code: str
    weight_loss_pct: Decimal
    cost_per_kg: Decimal
    effects: OperationEffects


@dataclass(frozen=True, slots=True)
class PackingResult:
    code: str
    unit_cost: Decimal
    expiry_date: date
    batch_closed: bool
    effects: OperationEffects


@dataclass(frozen=True, slots=True)
class PackingMaterials:
    bag: StockBalance
    label: StockBalance
    shelf_life_months: int


@dataclass(frozen=True, slots=True)
class PeriodFilters:
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class RoastBatchDetail:
    batch: dict[str, Any]
    packings: list[dict[str, Any]]
    movements: list[dict[str, Any]]


def _business_date(actor: User, requested: date | None) -> date:
    return resolve_business_date(requested, today(), has_permission(actor, Permission.BACKDATE_OPERATIONS))


def _ensure_period(filters: PeriodFilters) -> None:
    if filters.start_date > filters.end_date:
        raise BusinessRuleError("A data inicial deve ser anterior à data final.")


def _roast_limits(connection: Connection) -> RoastLimits:
    values = decimal_settings(connection, list(ROAST_LIMIT_SETTINGS.values()))
    return RoastLimits(**{field: values[key] for field, key in ROAST_LIMIT_SETTINGS.items()})


def _next_code(connection: Connection, table: str, letter: str, day: date) -> str:
    sequence = production_repository.next_daily_sequence(connection, table, daily_prefix(letter, day))
    return daily_code(letter, day, sequence)


def get_roast_limits(actor: User) -> RoastLimits:
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    with transaction(actor.email) as connection:
        return _roast_limits(connection)


def _ensure_harvest_origin(connection: Connection, data: HarvestInput) -> None:
    origin = production_repository.find_coffee_origin(connection, data.green_coffee_id)
    if origin is None or not origin["is_active"]:
        raise BusinessRuleError("Café verde não encontrado ou inativo.")
    if not origin["is_own"]:
        raise BusinessRuleError("Colheita só para café da fazenda própria. Café de parceiro entra por compra.")
    if data.service_supplier_id is not None:
        supply_type = partners_repository.find_supplier_supply_type(connection, data.service_supplier_id)
        if supply_type is not SupplyType.SERVICE:
            raise BusinessRuleError("O fornecedor do beneficiamento deve ser um fornecedor de serviços.")


def register_harvest(actor: User, data: HarvestInput, harvest_date: date | None = None) -> HarvestResult:
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    harvest_date = _business_date(actor, harvest_date)
    data = validate_harvest(data, harvest_date)
    with transaction(actor.email) as connection:
        _ensure_harvest_origin(connection, data)
        number = production_repository.next_harvest_number(connection, harvest_date.year)
        harvest_id = production_repository.insert_harvest(
            connection,
            {
                "number": number,
                "green_coffee_id": data.green_coffee_id,
                "harvest_date": harvest_date,
                "quantity_kg": data.quantity_kg,
                "total_cost": data.total_cost,
                "service_supplier_id": data.service_supplier_id,
                "due_date": data.due_date,
                "notes": data.notes,
                "user_email": actor.email,
            },
        )
        change = record_movement(
            connection,
            actor.email,
            MovementRequest(
                item=StockItemRef(StockItemKind.GREEN_COFFEE, data.green_coffee_id),
                movement_type=MovementType.HARVEST_IN,
                quantity=data.quantity_kg,
                movement_date=harvest_date,
                source_module=SourceModule.PRODUCTION,
                source_id=harvest_id,
                unit_cost=harvest_unit_cost(data.total_cost, data.quantity_kg),
            ),
        )
        description = f"Colheita {number} · {format_decimal(data.quantity_kg, 3)} kg"
        entry_id = finance_repository.insert_entry(
            connection,
            {
                "entry_type": EntryType.PAYABLE.value,
                "category_id": require_system_category_id(connection, HARVEST_CATEGORY),
                "description": description,
                "amount": data.total_cost,
                "accrual_date": harvest_date,
                "due_date": data.due_date,
                "source_module": SourceModule.PRODUCTION.value,
                "source_id": harvest_id,
                "supplier_id": data.service_supplier_id,
                "user_email": actor.email,
            },
        )
    entry = EntryChange(entry_id, EntryType.PAYABLE, description, data.total_cost, data.due_date)
    return HarvestResult(number, OperationEffects(stock=[change], entries=[entry]))


def roast(actor: User, data: RoastInput, roast_date: date | None = None) -> RoastResult:
    """RF-OPE-02. Roasting is physical and irreversible, so a batch is never reversed or edited."""
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    roast_date = _business_date(actor, roast_date)
    with transaction(actor.email) as connection:
        data = validate_roast(data, _roast_limits(connection))
        green_item = StockItemRef(StockItemKind.GREEN_COFFEE, data.green_coffee_id)
        green = lock_balance(connection, green_item)
        origin = production_repository.find_coffee_origin(connection, data.green_coffee_id)
        if not origin["is_active"]:
            raise BusinessRuleError(f"{green.label} está inativo e não pode ser torrado.")
        cost_per_kg = roasted_cost_per_kg(data.green_weight_kg, green.unit_cost, data.roasted_weight_kg)
        code = _next_code(connection, "roast_batches", "T", roast_date)
        batch_id = production_repository.insert_roast_batch(
            connection,
            {
                "code": code,
                "green_coffee_id": data.green_coffee_id,
                "roast_profile": data.roast_profile.value,
                "roast_date": roast_date,
                "green_weight_kg": data.green_weight_kg,
                "roasted_weight_kg": data.roasted_weight_kg,
                "green_cost_per_kg": green.unit_cost,
                "cost_per_kg": cost_per_kg,
                "stock_kg": Decimal("0"),
                "location": data.location,
                "roast_time_min": data.roast_time_min,
                "end_temperature_c": data.end_temperature_c,
                "notes": data.notes,
                "user_email": actor.email,
            },
        )
        movements = [
            (green_item, MovementType.ROAST_OUT, -data.green_weight_kg),
            (StockItemRef(StockItemKind.ROAST_BATCH, batch_id), MovementType.ROAST_IN, data.roasted_weight_kg),
        ]
        changes = [
            record_movement(
                connection,
                actor.email,
                MovementRequest(item, movement_type, quantity, roast_date, SourceModule.PRODUCTION, batch_id),
            )
            for item, movement_type, quantity in movements
        ]
    loss = weight_loss_pct(data.green_weight_kg, data.roasted_weight_kg)
    return RoastResult(code, loss, cost_per_kg, OperationEffects(stock=changes))


def _packing_product(connection: Connection, product_id: int) -> dict[str, Any]:
    product = production_repository.find_packing_product(connection, product_id)
    if product is None or not product["is_active"]:
        raise BusinessRuleError("Produto não encontrado ou inativo.")
    return product


def _locked_batch(connection: Connection, roast_batch_id: int) -> dict[str, Any]:
    batch = production_repository.find_roast_batch(connection, roast_batch_id, for_update=True)
    if batch is None:
        raise BusinessRuleError("Lote torrado não encontrado. Atualize a página e tente de novo.")
    return batch


def _batch_source(batch: dict[str, Any]) -> PackingBatchSource:
    return PackingBatchSource(
        batch["code"],
        RoastBatchStatus(batch["status"]),
        batch["green_coffee_id"],
        RoastProfile(batch["roast_profile"]),
        batch["roast_date"],
    )


def pack(actor: User, data: PackingInput, packing_date: date | None = None) -> PackingResult:
    """RF-OPE-03: consumes roasted coffee, bags and labels and adds finished bags to the product."""
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    data = validate_packing(data)
    packing_date = _business_date(actor, packing_date)
    with transaction(actor.email) as connection:
        product = _packing_product(connection, data.product_id)
        batch = _locked_batch(connection, data.roast_batch_id)
        ensure_batch_fits_product(
            _batch_source(batch),
            PackingProduct(
                product["label"], product["green_coffee_id"], RoastProfile(product["roast_profile"]),
                product["weight_g"],
            ),
            packing_date,
        )  # fmt: skip
        consumed_kg = packing_consumed_kg(data.bag_count, product["weight_g"])
        bag_count = Decimal(data.bag_count)
        batch_item = StockItemRef(StockItemKind.ROAST_BATCH, batch["id"])
        packaging = sorted({product["bag_id"], product["label_id"]})
        balances = {item_id: lock_balance(connection, StockItemRef(StockItemKind.PACKAGING_ITEM, item_id))
                    for item_id in packaging}  # fmt: skip
        batch_balance = lock_balance(connection, batch_item)
        shortages = find_shortages(
            [(batch_balance, consumed_kg), (balances[product["bag_id"]], bag_count),
             (balances[product["label_id"]], bag_count)]
        )  # fmt: skip
        if shortages:
            raise BusinessRuleError(describe_shortages(shortages))
        coffee_cost = packed_coffee_unit_cost(
            product["weight_g"], batch["green_weight_kg"], batch["green_cost_per_kg"], batch["roasted_weight_kg"]
        )
        bag_cost = balances[product["bag_id"]].unit_cost
        label_cost = balances[product["label_id"]].unit_cost
        code = _next_code(connection, "packing_batches", "E", packing_date)
        expiry_date = add_months(packing_date, int_setting(connection, SHELF_LIFE_SETTING))
        packing_id = production_repository.insert_packing_batch(
            connection,
            {
                "code": code,
                "roast_batch_id": batch["id"],
                "product_id": product["id"],
                "packing_date": packing_date,
                "expiry_date": expiry_date,
                "bag_count": data.bag_count,
                "consumed_kg": consumed_kg,
                "coffee_unit_cost": coffee_cost,
                "bag_unit_cost": bag_cost,
                "label_unit_cost": label_cost,
                "days_since_roast": (packing_date - batch["roast_date"]).days,
                "user_email": actor.email,
            },
        )
        unit_cost = coffee_cost + bag_cost + label_cost
        movements = [
            (batch_item, MovementType.PACKING_OUT, -consumed_kg, None),
            (StockItemRef(StockItemKind.PACKAGING_ITEM, product["bag_id"]), MovementType.PACKING_OUT, -bag_count, None),
            (StockItemRef(StockItemKind.PACKAGING_ITEM, product["label_id"]), MovementType.PACKING_OUT, -bag_count,
             None),
            (StockItemRef(StockItemKind.PRODUCT, product["id"]), MovementType.PACKING_IN, bag_count, unit_cost),
        ]  # fmt: skip
        changes = [
            record_movement(
                connection,
                actor.email,
                MovementRequest(
                    item, movement_type, quantity, packing_date, SourceModule.PRODUCTION, packing_id, unit_cost=cost
                ),
            )
            for item, movement_type, quantity, cost in movements
        ]
        batch_closed = changes[0].after == 0
        if batch_closed:
            production_repository.close_roast_batch(connection, batch["id"])
    return PackingResult(code, unit_cost, expiry_date, batch_closed, OperationEffects(stock=changes))


def close_roast_batch(actor: User, roast_batch_id: int, notes: str) -> OperationEffects:
    """RF-EST-05: writes the leftover off as loss and closes the batch."""
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    notes = require_text(notes, "Explique o encerramento na observação.")
    with transaction(actor.email) as connection:
        batch = _locked_batch(connection, roast_batch_id)
        if RoastBatchStatus(batch["status"]) is RoastBatchStatus.CLOSED:
            raise BusinessRuleError(f"O lote {batch['code']} já está encerrado.")
        smallest_bag = production_repository.smallest_compatible_bag_g(
            connection, batch["green_coffee_id"], batch["roast_profile"]
        )
        if not can_close_batch(batch["stock_kg"], smallest_bag):
            raise BusinessRuleError(
                f"O lote {batch['code']} ainda tem {format_decimal(batch['stock_kg'], 3)} kg, o bastante para "
                f"pacotes de {smallest_bag} g. Envase o saldo ou registre a perda com um ajuste de inventário."
            )
        changes: list[StockChange] = []
        if batch["stock_kg"] > 0:
            changes.append(
                record_movement(
                    connection,
                    actor.email,
                    MovementRequest(
                        item=StockItemRef(StockItemKind.ROAST_BATCH, batch["id"]),
                        movement_type=MovementType.INVENTORY_ADJUSTMENT,
                        quantity=-batch["stock_kg"],
                        movement_date=today(),
                        source_module=SourceModule.PRODUCTION,
                        source_id=batch["id"],
                        reason=AdjustmentReason.LOSS,
                        notes=f"Encerramento do lote {batch['code']}: {notes}",
                    ),
                )
            )
        production_repository.close_roast_batch(connection, batch["id"])
    return OperationEffects(stock=changes)


def list_harvests(actor: User, filters: PeriodFilters) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    _ensure_period(filters)
    with transaction(actor.email) as connection:
        return production_repository.list_harvests(connection, filters.start_date, filters.end_date, today())


def list_own_coffees(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    with transaction(actor.email) as connection:
        return production_repository.list_own_coffees(connection)


def list_service_suppliers(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    with transaction(actor.email) as connection:
        return partners_repository.list_supplier_options(connection, SupplyType.SERVICE)


def list_roastable_coffees(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    with transaction(actor.email) as connection:
        return production_repository.list_roastable_coffees(connection)


def list_roast_batches(
    actor: User, filters: PeriodFilters, statuses: tuple[RoastBatchStatus, ...]
) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    _ensure_period(filters)
    with transaction(actor.email) as connection:
        return production_repository.list_roast_batches(
            connection, filters.start_date, filters.end_date, [status.value for status in statuses], today()
        )


def get_roast_batch_detail(actor: User, roast_batch_id: int) -> RoastBatchDetail:
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    with transaction(actor.email) as connection:
        batch = production_repository.find_roast_batch(connection, roast_batch_id)
        if batch is None:
            raise BusinessRuleError("Lote torrado não encontrado.")
        movements = inventory_repository.list_item_movements(
            connection, StockItemRef(StockItemKind.ROAST_BATCH, roast_batch_id), date.min, date.max
        )
        return RoastBatchDetail(batch, production_repository.list_batch_packings(connection, roast_batch_id), movements)


def list_stale_roast_batches(actor: User) -> tuple[int, list[dict[str, Any]]]:
    """RF-EST-02: open batches waiting longer than the freshness limit."""
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    with transaction(actor.email) as connection:
        alert_days = int_setting(connection, FRESHNESS_SETTING)
        return alert_days, production_repository.list_stale_roast_batches(connection, today(), alert_days)


def get_freshness_alert_days(actor: User) -> int:
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    with transaction(actor.email) as connection:
        return int_setting(connection, FRESHNESS_SETTING)


def list_packable_products(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    with transaction(actor.email) as connection:
        return production_repository.list_packable_products(connection)


def list_compatible_batches(actor: User, product_id: int) -> list[dict[str, Any]]:
    """Open batches of the product's coffee and roast profile, oldest first (FEFO)."""
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    with transaction(actor.email) as connection:
        product = _packing_product(connection, product_id)
        return production_repository.list_compatible_batches(
            connection, product["green_coffee_id"], product["roast_profile"], today()
        )


def get_packing_materials(actor: User, product_id: int) -> PackingMaterials:
    ensure_permission(actor, Permission.MANAGE_PRODUCTION)
    with transaction(actor.email) as connection:
        product = _packing_product(connection, product_id)
        bag, label = (
            inventory_repository.find_stock_balance(connection, StockItemRef(StockItemKind.PACKAGING_ITEM, item_id))
            for item_id in (product["bag_id"], product["label_id"])
        )
        return PackingMaterials(bag, label, int_setting(connection, SHELF_LIFE_SETTING))


def list_packing_batches(actor: User, filters: PeriodFilters) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.VIEW_PRODUCTION)
    _ensure_period(filters)
    with transaction(actor.email) as connection:
        return production_repository.list_packing_batches(connection, filters.start_date, filters.end_date)
