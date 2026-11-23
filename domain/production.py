import calendar
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.catalog import RoastProfile
from domain.fields import clean_text
from domain.inventory import StockBalance, StockItemKind, format_quantity
from domain.numbers import format_decimal, round_kilograms, round_unit_cost

HARVEST_DEFAULT_TERM_DAYS = 30
GRAMS_PER_KILOGRAM = Decimal("1000")


class RoastBatchStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class HarvestInput:
    green_coffee_id: int | None
    quantity_kg: Decimal
    total_cost: Decimal
    service_supplier_id: int | None = None
    due_date: date | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class RoastLimits:
    min_green_kg: Decimal
    capacity_kg: Decimal
    warn_min_pct: Decimal
    warn_max_pct: Decimal
    block_min_pct: Decimal
    block_max_pct: Decimal


@dataclass(frozen=True, slots=True)
class RoastInput:
    green_coffee_id: int | None
    roast_profile: RoastProfile
    green_weight_kg: Decimal
    roasted_weight_kg: Decimal
    unusual_loss_confirmed: bool = False
    roast_time_min: Decimal | None = None
    end_temperature_c: Decimal | None = None
    location: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class PackingInput:
    product_id: int | None
    roast_batch_id: int | None
    bag_count: int


@dataclass(frozen=True, slots=True)
class PackingProduct:
    label: str
    green_coffee_id: int
    roast_profile: RoastProfile
    weight_g: int


@dataclass(frozen=True, slots=True)
class PackingBatchSource:
    code: str
    status: RoastBatchStatus
    green_coffee_id: int
    roast_profile: RoastProfile
    roast_date: date


@dataclass(frozen=True, slots=True)
class Shortage:
    label: str
    kind: StockItemKind
    available: Decimal
    required: Decimal


def validate_harvest(data: HarvestInput, harvest_date: date) -> HarvestInput:
    if data.green_coffee_id is None:
        raise BusinessRuleError("Selecione o café verde da fazenda própria.")
    if data.quantity_kg is None or data.quantity_kg <= 0:
        raise BusinessRuleError("Informe a quantidade colhida em kg.")
    if data.total_cost is None or data.total_cost <= 0:
        raise BusinessRuleError("Informe o custo total da colheita e do beneficiamento.")
    due_date = data.due_date or harvest_date + timedelta(days=HARVEST_DEFAULT_TERM_DAYS)
    if due_date < harvest_date:
        raise BusinessRuleError("O vencimento não pode ser anterior à data da colheita.")
    return replace(data, quantity_kg=round_kilograms(data.quantity_kg), due_date=due_date, notes=clean_text(data.notes))


def harvest_unit_cost(total_cost: Decimal, quantity_kg: Decimal) -> Decimal:
    return round_unit_cost(total_cost / quantity_kg)


def weight_loss_pct(green_weight_kg: Decimal, roasted_weight_kg: Decimal) -> Decimal:
    return ((green_weight_kg - roasted_weight_kg) / green_weight_kg * 100).quantize(Decimal("0.01"))


def roasted_cost_per_kg(green_weight_kg: Decimal, green_cost_per_kg: Decimal, roasted_weight_kg: Decimal) -> Decimal:
    """RN-09: the weight lost in the roaster is absorbed by the roasted kilogram."""
    return round_unit_cost(green_weight_kg * green_cost_per_kg / roasted_weight_kg)


def is_unusual_weight_loss(loss_pct: Decimal, limits: RoastLimits) -> bool:
    return not limits.warn_min_pct <= loss_pct <= limits.warn_max_pct


def _percent(value: Decimal) -> str:
    return f"{format_decimal(value, 2)}%"


def validate_roast(data: RoastInput, limits: RoastLimits) -> RoastInput:
    if data.green_coffee_id is None:
        raise BusinessRuleError("Selecione o café verde.")
    green, roasted = data.green_weight_kg, data.roasted_weight_kg
    if green is None or not limits.min_green_kg <= green <= limits.capacity_kg:
        raise BusinessRuleError(
            f"O peso verde por torra deve ficar entre {format_decimal(limits.min_green_kg, 0)} e "
            f"{format_decimal(limits.capacity_kg, 0)} kg (capacidade do torrador). Divida em mais bateladas."
        )
    if roasted is None or not 0 < roasted < green:
        raise BusinessRuleError("O peso torrado deve ser maior que zero e menor que o peso verde.")
    loss = weight_loss_pct(round_kilograms(green), round_kilograms(roasted))
    if not limits.block_min_pct <= loss <= limits.block_max_pct:
        raise BusinessRuleError(
            f"Quebra de {_percent(loss)} fora do possível ({_percent(limits.block_min_pct)} a "
            f"{_percent(limits.block_max_pct)}). Confira os pesos digitados."
        )
    if is_unusual_weight_loss(loss, limits) and not data.unusual_loss_confirmed:
        raise BusinessRuleError(
            f"Quebra de {_percent(loss)} fora da faixa usual ({_percent(limits.warn_min_pct)} a "
            f"{_percent(limits.warn_max_pct)}). Confirme que os pesos estão corretos."
        )
    if data.roast_time_min is not None and data.roast_time_min <= 0:
        raise BusinessRuleError("O tempo de torra deve ser maior que zero.")
    return replace(
        data,
        green_weight_kg=round_kilograms(green),
        roasted_weight_kg=round_kilograms(roasted),
        location=clean_text(data.location),
        notes=clean_text(data.notes),
    )


def daily_prefix(letter: str, day: date) -> str:
    return f"{letter}-{day:%Y%m%d}"


def daily_code(letter: str, day: date, sequence: int) -> str:
    return f"{daily_prefix(letter, day)}-{sequence:02d}"


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def packing_consumed_kg(bag_count: int, weight_g: int) -> Decimal:
    return round_kilograms(Decimal(bag_count) * weight_g / GRAMS_PER_KILOGRAM)


def packed_coffee_unit_cost(
    weight_g: int, green_weight_kg: Decimal, green_cost_per_kg: Decimal, roasted_weight_kg: Decimal
) -> Decimal:
    """Coffee share of one bag (RN-12), from the batch's source values so the kg cost is rounded only once."""
    return round_unit_cost(weight_g / GRAMS_PER_KILOGRAM * green_weight_kg * green_cost_per_kg / roasted_weight_kg)


def validate_packing(data: PackingInput) -> PackingInput:
    if data.product_id is None:
        raise BusinessRuleError("Selecione o produto a envasar.")
    if data.roast_batch_id is None:
        raise BusinessRuleError("Selecione o lote torrado.")
    if data.bag_count is None or data.bag_count < 1:
        raise BusinessRuleError("Informe quantos pacotes serão envasados.")
    return data


def ensure_batch_fits_product(batch: PackingBatchSource, product: PackingProduct, packing_date: date) -> None:
    """RN-11: what is printed on the bag must be what is inside it."""
    if batch.status is not RoastBatchStatus.OPEN:
        raise BusinessRuleError(f"O lote {batch.code} está encerrado e não pode ser envasado.")
    if batch.green_coffee_id != product.green_coffee_id or batch.roast_profile is not product.roast_profile:
        raise BusinessRuleError(
            f"O lote {batch.code} não é do mesmo café e perfil de torra de {product.label}. Escolha um lote compatível."
        )
    if packing_date < batch.roast_date:
        raise BusinessRuleError("A data do envase não pode ser anterior à data da torra do lote.")


def find_shortages(requirements: list[tuple[StockBalance, Decimal]]) -> list[Shortage]:
    return [
        Shortage(balance.label, balance.item.kind, balance.stock, required)
        for balance, required in requirements
        if balance.stock < required
    ]


def describe_shortages(shortages: list[Shortage]) -> str:
    details = "; ".join(
        f"{shortage.label} tem {format_quantity(shortage.kind, shortage.available)} e precisa de "
        f"{format_quantity(shortage.kind, shortage.required)}"
        for shortage in shortages
    )
    return f"Falta material para o envase: {details}{'' if details.endswith('.') else '.'}"


def can_close_batch(stock_kg: Decimal, smallest_bag_g: int | None) -> bool:
    """RF-EST-05: only a residue smaller than the smallest compatible bag is written off as loss."""
    return smallest_bag_g is None or stock_kg * GRAMS_PER_KILOGRAM < smallest_bag_g
