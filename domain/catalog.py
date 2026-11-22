import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from core.errors import BusinessRuleError
from domain.fields import (
    clean_state,
    clean_text,
    ensure_between,
    ensure_not_negative,
    ensure_positive,
    require_text,
)

BAG_CAPACITIES_G: tuple[int, ...] = (250, 500, 1000)
COFFEE_CODE_PATTERN = re.compile(r"^[A-Z0-9]{2,10}$")
FIRST_HARVEST_YEAR = 2020
LAST_HARVEST_YEAR = 2100


class Process(StrEnum):
    NATURAL = "NATURAL"
    PULPED_NATURAL = "PULPED_NATURAL"
    WASHED = "WASHED"
    FERMENTED = "FERMENTED"


class PackagingKind(StrEnum):
    BAG = "BAG"
    LABEL = "LABEL"
    SHIPPING_BOX = "SHIPPING_BOX"


class RoastProfile(StrEnum):
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    DARK = "DARK"


class Grind(StrEnum):
    WHOLE_BEAN = "WHOLE_BEAN"
    ESPRESSO = "ESPRESSO"
    FILTER = "FILTER"
    FRENCH_PRESS = "FRENCH_PRESS"


SKU_ROAST_CODES: dict[RoastProfile, str] = {
    RoastProfile.LIGHT: "CLA",
    RoastProfile.MEDIUM: "MED",
    RoastProfile.DARK: "ESC",
}

SKU_GRIND_CODES: dict[Grind, str] = {
    Grind.WHOLE_BEAN: "GR",
    Grind.ESPRESSO: "ESP",
    Grind.FILTER: "COA",
    Grind.FRENCH_PRESS: "PRE",
}


@dataclass(frozen=True, slots=True)
class FarmInput:
    name: str
    city: str
    state: str
    producer: str
    is_own: bool
    supplier_id: int | None = None
    altitude_m: int | None = None


@dataclass(frozen=True, slots=True)
class GreenCoffeeInput:
    code: str
    name: str
    farm_id: int | None
    variety: str
    process: Process
    harvest_year: int
    sca_score: Decimal | None = None
    moisture_pct: Decimal | None = None
    min_stock_kg: Decimal = Decimal("0")
    location: str | None = None


@dataclass(frozen=True, slots=True)
class PackagingItemInput:
    name: str
    kind: PackagingKind
    capacity_g: int | None = None
    min_stock: int = 0
    location: str | None = None


@dataclass(frozen=True, slots=True)
class ProductInput:
    name: str
    green_coffee_id: int | None
    roast_profile: RoastProfile
    grind: Grind
    weight_g: int
    bag_id: int | None
    label_id: int | None
    price_local: Decimal
    price_online: Decimal
    price_wholesale: Decimal | None = None
    min_stock: int = 0
    location: str | None = None


@dataclass(frozen=True, slots=True)
class PackagingSpec:
    name: str
    kind: PackagingKind
    capacity_g: int | None


def validate_farm(data: FarmInput) -> FarmInput:
    if data.is_own and data.supplier_id is not None:
        raise BusinessRuleError("Fazenda própria não tem fornecedor. Remova o fornecedor ou marque como parceira.")
    if not data.is_own and data.supplier_id is None:
        raise BusinessRuleError("Fazenda parceira precisa do fornecedor que fatura o café.")
    ensure_between(data.altitude_m, 0, 3000, "A altitude deve ficar entre 0 e 3.000 m.")
    return replace(
        data,
        name=require_text(data.name, "Informe o nome da fazenda."),
        city=require_text(data.city, "Informe o município da fazenda."),
        state=clean_state(data.state, required=True),
        producer=require_text(data.producer, "Informe o produtor responsável."),
    )


def validate_green_coffee(data: GreenCoffeeInput) -> GreenCoffeeInput:
    code = (clean_text(data.code) or "").upper()
    if not COFFEE_CODE_PATTERN.match(code):
        raise BusinessRuleError("O código do café deve ter de 2 a 10 letras ou números, sem espaços (ex.: BVCAT).")
    if data.farm_id is None:
        raise BusinessRuleError("Selecione a fazenda de origem.")
    ensure_between(
        data.harvest_year,
        FIRST_HARVEST_YEAR,
        LAST_HARVEST_YEAR,
        f"A safra deve ser um ano a partir de {FIRST_HARVEST_YEAR}.",
    )
    ensure_between(data.sca_score, 60, 100, "A pontuação SCA deve ficar entre 60 e 100.")
    ensure_between(data.moisture_pct, 0, 20, "A umidade deve ficar entre 0 e 20%.")
    ensure_not_negative(data.min_stock_kg, "O estoque mínimo não pode ser negativo.")
    return replace(
        data,
        code=code,
        name=require_text(data.name, "Informe o nome comercial do café."),
        variety=require_text(data.variety, "Informe o varietal."),
        location=clean_text(data.location),
    )


def validate_packaging_item(data: PackagingItemInput) -> PackagingItemInput:
    capacity = data.capacity_g
    if data.kind is PackagingKind.BAG and capacity not in BAG_CAPACITIES_G:
        raise BusinessRuleError("A capacidade do pacote deve ser 250, 500 ou 1.000 g.")
    if data.kind is PackagingKind.SHIPPING_BOX:
        ensure_positive(capacity, "Informe a capacidade da caixa de envio em gramas.")
    if data.kind is PackagingKind.LABEL:
        capacity = None
    ensure_not_negative(data.min_stock, "O estoque mínimo não pode ser negativo.")
    return replace(
        data,
        name=require_text(data.name, "Informe o nome da embalagem."),
        capacity_g=capacity,
        location=clean_text(data.location),
    )


def validate_product(data: ProductInput, bag: PackagingSpec, label: PackagingSpec) -> ProductInput:
    if data.green_coffee_id is None:
        raise BusinessRuleError("Selecione o café verde de origem.")
    if data.weight_g not in BAG_CAPACITIES_G:
        raise BusinessRuleError("O peso do produto deve ser 250, 500 ou 1.000 g.")
    if bag.kind is not PackagingKind.BAG or bag.capacity_g != data.weight_g:
        raise BusinessRuleError(
            f"O pacote {bag.name} não serve para {data.weight_g} g. Escolha um pacote do mesmo peso."
        )
    if label.kind is not PackagingKind.LABEL:
        raise BusinessRuleError(f"{label.name} não é uma etiqueta.")
    ensure_positive(data.price_local, "Informe o preço de venda na loja.")
    ensure_positive(data.price_online, "Informe o preço de venda online.")
    if data.price_wholesale is not None:
        ensure_positive(data.price_wholesale, "O preço de atacado deve ser maior que zero ou ficar em branco.")
    ensure_not_negative(data.min_stock, "O estoque mínimo não pode ser negativo.")
    return replace(
        data,
        name=require_text(data.name, "Informe o nome do produto."),
        location=clean_text(data.location),
    )


def build_sku(coffee_code: str, roast_profile: RoastProfile, grind: Grind, weight_g: int) -> str:
    return f"CC-{coffee_code}-{SKU_ROAST_CODES[roast_profile]}-{SKU_GRIND_CODES[grind]}-{weight_g}"
