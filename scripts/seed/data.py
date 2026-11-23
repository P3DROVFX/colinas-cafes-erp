"""Fixed master data and business assumptions of the simulated history (spec section 13)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from domain.catalog import Grind, PackagingKind, Process, RoastProfile
from domain.partners import Segment

FULL_START = date(2026, 6, 1)
SMALL_DAYS = 14
SEED_NUMBER = 2026

NEW_CROP_DATE = date(2026, 8, 1)
NEW_CROP_PRICE_FACTOR = Decimal("1.18")
PRICE_INCREASE_DATE = date(2026, 10, 26)
PRICE_INCREASE_FACTOR = Decimal("1.08")
SHORTAGE_ITEM = "bag250"
SHORTAGE_BLOCK = (date(2026, 8, 15), date(2026, 10, 31))
SHORTAGE_DAYS = 10
DEFAULTED_CUSTOMER = "Cafeteria Pátio do Agreste"
DEFAULT_WINDOW = (date(2026, 9, 10), date(2026, 10, 20))
FRESHNESS_OVERROAST_DAYS = (date(2026, 9, 2), date(2026, 10, 6))
BLACK_FRIDAY_WARMUP = (date(2026, 11, 16), date(2026, 11, 22))
FATHERS_DAY_MONTH = 8

OPENING_BALANCES = {"BANK": Decimal("38000"), "CASH": Decimal("600")}


@dataclass(frozen=True)
class SupplierSeed:
    key: str
    name: str
    is_company: bool
    supply: str
    city: str
    state: str
    lead_time_days: int


SUPPLIERS = (
    SupplierSeed("boa_vista", "Sítio Boa Vista", False, "GREEN_COFFEE", "Taquaritinga do Norte", "PE", 7),
    SupplierSeed("chapada", "Fazenda Chapada Alta Ltda", True, "GREEN_COFFEE", "Piatã", "BA", 12),
    SupplierSeed("sul_minas", "Cooperativa Sul Mineira", True, "GREEN_COFFEE", "Carmo de Minas", "MG", 10),
    SupplierSeed("caparao", "Sítio Pico da Bandeira", False, "GREEN_COFFEE", "Alto Caparaó", "MG", 14),
    SupplierSeed("embala", "EmbalaCafé Ltda", True, "PACKAGING", "Caruaru", "PE", 8),
    SupplierSeed("beneficia", "Beneficiadora Agreste Ltda", True, "SERVICE", "Garanhuns", "PE", 3),
)


@dataclass(frozen=True)
class FarmSeed:
    key: str
    name: str
    city: str
    state: str
    producer: str
    altitude_m: int
    supplier: str | None


FARMS = (
    FarmSeed("colinas", "Fazenda Colinas", "Garanhuns", "PE", "Família Colinas", 950, None),
    FarmSeed("boa_vista", "Sítio Boa Vista", "Taquaritinga do Norte", "PE", "José Ferreira", 1000, "boa_vista"),
    FarmSeed("chapada", "Fazenda Chapada Alta", "Piatã", "BA", "Marina Rocha", 1250, "chapada"),
    FarmSeed("sul_minas", "Fazenda Serra Verde", "Carmo de Minas", "MG", "Antônio Pereira", 1150, "sul_minas"),
    FarmSeed("caparao", "Sítio Pico da Bandeira", "Alto Caparaó", "MG", "Luiza Martins", 1300, "caparao"),
)


@dataclass(frozen=True)
class CoffeeSeed:
    code: str
    name: str
    farm: str
    variety: str
    process: Process
    harvest_year: int
    sca: str
    moisture: str
    base_cost: Decimal
    opening_kg: Decimal = Decimal("0")
    available_from: date | None = None
    lot_kg: tuple[int, int] = (60, 90)


COFFEES = (
    CoffeeSeed("COLBOU", "Colinas Bourbon Amarelo", "colinas", "Bourbon Amarelo", Process.NATURAL, 2026, "84",
               "11.0", Decimal("31"), Decimal("60")),
    CoffeeSeed("BVCAT25", "Boa Vista Catuaí 2025", "boa_vista", "Catuaí Amarelo", Process.NATURAL, 2025, "84.5",
               "11.2", Decimal("52"), Decimal("170")),
    CoffeeSeed("BVCAT26", "Boa Vista Catuaí 2026", "boa_vista", "Catuaí Amarelo", Process.NATURAL, 2026, "85",
               "11.0", Decimal("52"), available_from=date(2026, 8, 3)),
    CoffeeSeed("CDCAT", "Chapada Catuaí Vermelho", "chapada", "Catuaí Vermelho", Process.PULPED_NATURAL, 2025,
               "85.5", "10.8", Decimal("58"), Decimal("90")),
    CoffeeSeed("SMMUN", "Serra Verde Mundo Novo", "sul_minas", "Mundo Novo", Process.NATURAL, 2025, "82",
               "11.4", Decimal("46"), Decimal("120")),
    CoffeeSeed("CPARA", "Caparaó Arara", "caparao", "Arara", Process.WASHED, 2026, "86", "13.5", Decimal("60"),
               available_from=date(2026, 8, 17)),
    CoffeeSeed("CDGEI", "Chapada Gesha Fermentado", "chapada", "Gesha", Process.FERMENTED, 2026, "88.5", "10.5",
               Decimal("110"), available_from=date(2026, 9, 1), lot_kg=(30, 30)),
)  # fmt: skip

NO_REORDER = frozenset({"BVCAT25", "COLBOU"})
ANOMALOUS_COFFEE = "CPARA"
HARVESTS = (
    (date(2026, 6, 17), Decimal("180")),
    (date(2026, 7, 15), Decimal("220")),
    (date(2026, 8, 12), Decimal("150")),
)
HARVEST_COST_PER_KG = Decimal("31")

WEIGHT_LOSS_RANGES = {
    RoastProfile.LIGHT: (Decimal("11.5"), Decimal("14")),
    RoastProfile.MEDIUM: (Decimal("14"), Decimal("17")),
    RoastProfile.DARK: (Decimal("17"), Decimal("20.5")),
}
ANOMALY_EXTRA_LOSS = Decimal("3")


@dataclass(frozen=True)
class PackagingSeed:
    key: str
    name: str
    kind: PackagingKind
    capacity_g: int | None
    min_stock: int
    opening: int
    cost: Decimal
    reorder_point: int
    order_quantity: int


PACKAGING = (
    PackagingSeed("bag250", "Pacote valvulado 250 g", PackagingKind.BAG, 250, 150, 420, Decimal("1.80"), 180, 500),
    PackagingSeed("bag500", "Pacote valvulado 500 g", PackagingKind.BAG, 500, 60, 150, Decimal("2.40"), 70, 200),
    PackagingSeed("bag1000", "Pacote valvulado 1 kg", PackagingKind.BAG, 1000, 60, 160, Decimal("3.20"), 70, 200),
    PackagingSeed("label", "Etiqueta padrão", PackagingKind.LABEL, None, 300, 1200, Decimal("0.35"), 350, 1200),
    PackagingSeed("box_s", "Caixa de envio P", PackagingKind.SHIPPING_BOX, 2000, 40, 150, Decimal("3.20"), 50, 200),
    PackagingSeed("box_l", "Caixa de envio G", PackagingKind.SHIPPING_BOX, 6000, 10, 40, Decimal("5.80"), 12, 50),
)


@dataclass(frozen=True)
class ProductSeed:
    coffee: str
    profile: RoastProfile
    grind: Grind
    weight_g: int
    price_local: str
    price_online: str
    price_wholesale: str | None
    popularity: int
    target: int


PRODUCTS = (
    ProductSeed("COLBOU", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 250, "44.90", "49.90", None, 9, 30),
    ProductSeed("COLBOU", RoastProfile.MEDIUM, Grind.ESPRESSO, 250, "44.90", "49.90", None, 6, 20),
    ProductSeed("COLBOU", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 1000, "149.90", "159.90", "118.00", 3, 18),
    ProductSeed("COLBOU", RoastProfile.DARK, Grind.ESPRESSO, 1000, "144.90", "154.90", "112.00", 3, 15),
    ProductSeed("COLBOU", RoastProfile.DARK, Grind.FILTER, 500, "79.90", "84.90", None, 3, 10),
    ProductSeed("BVCAT25", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 250, "49.90", "54.90", None, 8, 28),
    ProductSeed("BVCAT25", RoastProfile.MEDIUM, Grind.FILTER, 250, "49.90", "54.90", None, 6, 20),
    ProductSeed("BVCAT25", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 1000, "169.90", "179.90", "132.00", 3, 15),
    ProductSeed("BVCAT26", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 250, "49.90", "54.90", None, 8, 28),
    ProductSeed("BVCAT26", RoastProfile.MEDIUM, Grind.FILTER, 250, "49.90", "54.90", None, 6, 20),
    ProductSeed("BVCAT26", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 1000, "169.90", "179.90", "132.00", 3, 15),
    ProductSeed("CDCAT", RoastProfile.LIGHT, Grind.WHOLE_BEAN, 250, "54.90", "59.90", None, 4, 15),
    ProductSeed("CDCAT", RoastProfile.LIGHT, Grind.FILTER, 250, "54.90", "59.90", None, 3, 12),
    ProductSeed("SMMUN", RoastProfile.DARK, Grind.ESPRESSO, 250, "39.90", "44.90", None, 6, 20),
    ProductSeed("SMMUN", RoastProfile.DARK, Grind.WHOLE_BEAN, 1000, "129.90", "139.90", "98.00", 4, 20),
    ProductSeed("SMMUN", RoastProfile.MEDIUM, Grind.FRENCH_PRESS, 500, "72.90", "77.90", None, 2, 8),
    ProductSeed("CPARA", RoastProfile.MEDIUM, Grind.WHOLE_BEAN, 250, "56.90", "61.90", None, 4, 15),
    ProductSeed("CPARA", RoastProfile.MEDIUM, Grind.FILTER, 500, "104.90", "109.90", None, 2, 8),
    ProductSeed("CDGEI", RoastProfile.LIGHT, Grind.WHOLE_BEAN, 250, "89.90", "94.90", None, 2, 8),
)

GRIND_NAMES = {Grind.WHOLE_BEAN: "Em grãos", Grind.ESPRESSO: "Moagem fina", Grind.FILTER: "Moagem média",
               Grind.FRENCH_PRESS: "Moagem grossa"}  # fmt: skip
PROFILE_NAMES = {
    RoastProfile.LIGHT: "Torra Clara",
    RoastProfile.MEDIUM: "Torra Média",
    RoastProfile.DARK: "Torra Escura",
}


@dataclass(frozen=True)
class CompanySeed:
    name: str
    segment: Segment
    city: str
    term_days: int
    credit_limit: Decimal
    weight: int


COMPANIES = (
    CompanySeed("Café Gravatá Bistrô", Segment.COFFEE_SHOP, "Gravatá", 28, Decimal("8000"), 30),
    CompanySeed("Restaurante Mandacaru", Segment.RESTAURANT, "Recife", 21, Decimal("7000"), 24),
    CompanySeed(DEFAULTED_CUSTOMER, Segment.COFFEE_SHOP, "Garanhuns", 21, Decimal("3000"), 9),
    CompanySeed("Empório Serra Agreste", Segment.EMPORIUM, "Caruaru", 28, Decimal("3500"), 7),
    CompanySeed("Café do Largo", Segment.COFFEE_SHOP, "Olinda", 14, Decimal("2500"), 6),
    CompanySeed("Padaria Flor de Lis", Segment.COMPANY, "Garanhuns", 14, Decimal("2000"), 5),
    CompanySeed("Hotel Canta Galo", Segment.COMPANY, "Gravatá", 28, Decimal("3000"), 5),
    CompanySeed("Empório Recife Antigo", Segment.EMPORIUM, "Recife", 21, Decimal("2500"), 4),
    CompanySeed("Bistrô Bonito", Segment.RESTAURANT, "Bonito", 14, Decimal("1500"), 4),
    CompanySeed("Coworking Ponte Nova", Segment.COMPANY, "Recife", 14, Decimal("1500"), 3),
    CompanySeed("Café Sertão Moderno", Segment.COFFEE_SHOP, "Arcoverde", 21, Decimal("2000"), 3),
)

FIRST_NAMES = (
    "Ana", "Bruno", "Carla", "Daniel", "Elisa", "Fábio", "Gabriela", "Henrique", "Isabela", "João", "Karina", "Lucas",
    "Mariana", "Nicolas", "Olívia", "Pedro", "Quésia", "Rafael", "Sofia", "Thiago", "Úrsula", "Vinícius", "Yasmin",
    "Wesley", "Beatriz", "Caio", "Débora", "Eduardo", "Fernanda", "Gustavo", "Helena", "Igor",
)  # fmt: skip
LAST_NAMES = (
    "Souza", "Lima", "Albuquerque", "Barros", "Cavalcanti", "Duarte", "Ferraz", "Gomes", "Lins", "Macedo", "Nunes",
    "Oliveira", "Pessoa", "Queiroz", "Rocha", "Santana", "Tavares", "Vasconcelos", "Wanderley", "Xavier",
)  # fmt: skip
CITIES = (("Garanhuns", "PE", 5), ("Recife", "PE", 4), ("Caruaru", "PE", 2), ("Olinda", "PE", 1),
          ("João Pessoa", "PB", 1), ("Maceió", "AL", 1), ("São Paulo", "SP", 1), ("Salvador", "BA", 1))  # fmt: skip
STREETS = ("Rua das Flores", "Av. Rui Barbosa", "Rua do Sol", "Rua Dom José", "Av. Santo Antônio", "Rua da Aurora",
           "Rua Siqueira Campos", "Av. Caxangá", "Rua Treze de Maio", "Rua do Imperador")  # fmt: skip
CONSUMER_COUNT = 64


@dataclass(frozen=True)
class ExpenseSeed:
    category: str
    description: str
    due_day: int
    amount_range: tuple[int, int]


MONTHLY_EXPENSES = (
    ExpenseSeed("Aluguel", "Aluguel da loja e torrefação", 5, (1600, 1600)),
    ExpenseSeed("Salários e pró-labore", "Salários e pró-labore", 5, (4200, 4200)),
    ExpenseSeed("Energia elétrica", "Energia elétrica", 12, (480, 690)),
    ExpenseSeed("Gás do torrador", "Gás do torrador", 15, (260, 380)),
    ExpenseSeed("Marketing", "Anúncios e redes sociais", 20, (300, 650)),
    ExpenseSeed("Plataforma de e-commerce", "Mensalidade da loja virtual", 10, (189, 189)),
)
ONE_OFF_ENTRIES = (
    (date(2026, 8, 22), "Outras receitas", "Curso de barista – turma de agosto", Decimal("1350"), 0),
    (date(2026, 9, 14), "Manutenção de equipamentos", "Manutenção do torrador", Decimal("950"), 10),
)

SALES_PER_DAY = {"LOCAL": Decimal("3.0"), "ONLINE": Decimal("1.9"), "WHOLESALE": Decimal("0.5")}
MONTH_FACTORS = {6: Decimal("1.10"), 7: Decimal("1.15"), 8: Decimal("1.05"), 9: Decimal("0.85"), 10: Decimal("0.90"),
                 11: Decimal("1.0")}  # fmt: skip
ONLINE_MONTHLY_GROWTH = Decimal("0.11")
FATHERS_DAY_ONLINE_FACTOR = Decimal("1.4")
BLACK_FRIDAY_ONLINE_FACTOR = Decimal("1.6")
FREE_SHIPPING_FROM = Decimal("199")
SHIPPING_PRICES = ((500, Decimal("22.90")), (1000, Decimal("26.90")), (999999, Decimal("32.90")))
