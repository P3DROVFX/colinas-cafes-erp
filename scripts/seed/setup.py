"""Creates users, master data and opening balances through the service layer."""

import random
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from domain.access import Role, User
from domain.brazil import PersonType
from domain.catalog import FarmInput, GreenCoffeeInput, PackagingItemInput, ProductInput
from domain.finance import AccountKind, FinancialAccountInput
from domain.inventory import AdjustmentReason, StockItemKind, StockItemRef
from domain.partners import CustomerInput, Segment, SupplierInput, SupplyType
from scripts.seed import data
from services import catalog as catalog_service
from services import finance_setup as finance_setup_service
from services import inventory as inventory_service
from services import partners as partners_service
from services import settings as settings_service
from services import users as users_service
from services.inventory import AdjustmentInput

ADMIN_EMAIL = "carga@colinas.com.br"
STAFF = {
    Role.MANAGER: ("gerente@colinas.com.br", "Helena Cavalcanti"),
    Role.PRODUCTION: ("producao@colinas.com.br", "Rafael Lins"),
    Role.SALES: ("comercial@colinas.com.br", "Mariana Tavares"),
    Role.FINANCE: ("financeiro@colinas.com.br", "Igor Duarte"),
}


@dataclass
class ProductState:
    id: int
    seed: data.ProductSeed
    coffee_id: int
    sku_input: ProductInput


@dataclass
class SeedContext:
    rng: random.Random
    admin: User
    staff: dict[Role, User]
    supplier_ids: dict[str, int]
    coffee_ids: dict[str, int]
    packaging_ids: dict[str, int]
    products: list[ProductState] = field(default_factory=list)
    consumer_ids: list[int] = field(default_factory=list)
    company_ids: dict[str, int] = field(default_factory=dict)
    walk_in_id: int = 0

    def user(self, role: Role) -> User:
        return self.staff[role]

    def coffee_code(self, coffee_id: int) -> str:
        return next(code for code, value in self.coffee_ids.items() if value == coffee_id)


def _check_digit(digits: list[int], weights: list[int]) -> int:
    remainder = sum(digit * weight for digit, weight in zip(digits, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def make_cpf(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(9)]
    digits.append(_check_digit(digits, list(range(10, 1, -1))))
    digits.append(_check_digit(digits, list(range(11, 1, -1))))
    return "".join(map(str, digits))


def make_cnpj(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    digits.append(_check_digit(digits, weights))
    digits.append(_check_digit(digits, [6, *weights]))
    return "".join(map(str, digits))


def _create_users() -> tuple[User, dict[Role, User]]:
    admin = users_service.sign_in(ADMIN_EMAIL, "Carga do histórico", frozenset({ADMIN_EMAIL}))
    staff = {}
    for role, (email, name) in STAFF.items():
        user = users_service.sign_in(email, name, frozenset())
        users_service.update_user_access(admin, user.id, role, True)
        staff[role] = users_service.get_active_user(email)
    return admin, staff


def _create_partners(rng: random.Random, manager: User) -> dict[str, int]:
    ids = {}
    for supplier in data.SUPPLIERS:
        person_type = PersonType.COMPANY if supplier.is_company else PersonType.INDIVIDUAL
        document = make_cnpj(rng) if supplier.is_company else make_cpf(rng)
        ids[supplier.key] = partners_service.create_supplier(
            manager,
            SupplierInput(supplier.name, person_type, document, SupplyType(supplier.supply), city=supplier.city,
                          state=supplier.state, lead_time_days=supplier.lead_time_days),
        )  # fmt: skip
    return ids


def _create_coffees(manager: User, supplier_ids: dict[str, int]) -> dict[str, int]:
    farm_ids = {
        farm.key: catalog_service.create_farm(
            manager,
            FarmInput(
                farm.name,
                farm.city,
                farm.state,
                farm.producer,
                farm.supplier is None,
                supplier_ids.get(farm.supplier),
                farm.altitude_m,
            ),
        )  # fmt: skip
        for farm in data.FARMS
    }
    return {
        coffee.code: catalog_service.create_green_coffee(
            manager,
            GreenCoffeeInput(
                coffee.code,
                coffee.name,
                farm_ids[coffee.farm],
                coffee.variety,
                coffee.process,
                coffee.harvest_year,
                Decimal(coffee.sca),
                Decimal(coffee.moisture),
                Decimal("20"),
                "Armazém verde",
            ),
        )  # fmt: skip
        for coffee in data.COFFEES
    }


def _create_packaging(manager: User) -> dict[str, int]:
    return {
        item.key: catalog_service.create_packaging_item(
            manager, PackagingItemInput(item.name, item.kind, item.capacity_g, item.min_stock, "Estoque de embalagens")
        )
        for item in data.PACKAGING
    }


def product_input(seed: data.ProductSeed, coffee_id: int, packaging_ids: dict[str, int]) -> ProductInput:
    coffee = next(item for item in data.COFFEES if item.code == seed.coffee)
    weight = "1 kg" if seed.weight_g == 1000 else f"{seed.weight_g} g"
    name = f"{coffee.name} – {data.PROFILE_NAMES[seed.profile]} – {data.GRIND_NAMES[seed.grind]} – {weight}"
    return ProductInput(
        name, coffee_id, seed.profile, seed.grind, seed.weight_g, packaging_ids[f"bag{seed.weight_g}"],
        packaging_ids["label"], Decimal(seed.price_local), Decimal(seed.price_online),
        Decimal(seed.price_wholesale) if seed.price_wholesale else None, seed.target // 3, "Loja – prateleira",
    )  # fmt: skip


def _create_products(context: SeedContext) -> None:
    for seed in data.PRODUCTS:
        coffee_id = context.coffee_ids[seed.coffee]
        sku_input = product_input(seed, coffee_id, context.packaging_ids)
        product_id = catalog_service.create_product(context.user(Role.MANAGER), sku_input)
        context.products.append(ProductState(product_id, seed, coffee_id, sku_input))


def _create_customers(context: SeedContext) -> None:
    rng, seller = context.rng, context.user(Role.SALES)
    cities = [city for city, _, weight in data.CITIES for _ in range(weight)]
    states = {city: state for city, state, _ in data.CITIES}
    used_names: set[str] = set()
    while len(context.consumer_ids) < data.CONSUMER_COUNT:
        name = f"{rng.choice(data.FIRST_NAMES)} {rng.choice(data.LAST_NAMES)}"
        if name in used_names:
            continue
        used_names.add(name)
        city = rng.choice(cities)
        address = f"{rng.choice(data.STREETS)}, {rng.randint(10, 990)}"
        document = make_cpf(rng) if rng.random() < 0.5 else None
        email = f"{name.lower().replace(' ', '.')}@email.com".encode("ascii", "ignore").decode()
        context.consumer_ids.append(
            partners_service.create_customer(
                seller,
                CustomerInput(name, PersonType.INDIVIDUAL, Segment.CONSUMER, document, email,
                              f"(81) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}", address, city,
                              states[city]),
            )
        )  # fmt: skip
    manager = context.user(Role.MANAGER)
    for company in data.COMPANIES:
        context.company_ids[company.name] = partners_service.create_customer(
            manager,
            CustomerInput(company.name, PersonType.COMPANY, company.segment, make_cnpj(rng), None,
                          "(81) 3333-0000", f"{rng.choice(data.STREETS)}, {rng.randint(10, 990)}", company.city,
                          "PE", company.term_days, company.credit_limit),
        )  # fmt: skip
    walk_in = next(row for row in partners_service.list_customers(manager) if row["is_system"])
    context.walk_in_id = walk_in["id"]


def _set_opening_balances(admin: User, start: date) -> None:
    for account in finance_setup_service.list_financial_accounts(admin):
        if account["is_system"]:
            kind = AccountKind(account["kind"])
            finance_setup_service.update_financial_account(
                admin, account["id"],
                FinancialAccountInput(account["name"], kind, data.OPENING_BALANCES[kind.value], start),
            )  # fmt: skip
    settings_service.update_settings(admin, {"operation_start_date": start.isoformat()})


def _set_opening_stock(context: SeedContext) -> None:
    manager = context.user(Role.MANAGER)
    notes = "Implantação do saldo inicial na entrada do sistema"
    for coffee in data.COFFEES:
        if coffee.opening_kg:
            inventory_service.adjust_inventory(
                manager,
                AdjustmentInput(StockItemRef(StockItemKind.GREEN_COFFEE, context.coffee_ids[coffee.code]),
                                AdjustmentReason.OPENING, notes, counted_stock=coffee.opening_kg,
                                unit_cost=coffee.base_cost),
            )  # fmt: skip
    for item in data.PACKAGING:
        inventory_service.adjust_inventory(
            manager,
            AdjustmentInput(StockItemRef(StockItemKind.PACKAGING_ITEM, context.packaging_ids[item.key]),
                            AdjustmentReason.OPENING, notes, counted_stock=Decimal(item.opening),
                            unit_cost=item.cost - Decimal("0.05")),
        )  # fmt: skip


def create_master_data(rng: random.Random, start: date) -> SeedContext:
    admin, staff = _create_users()
    manager = staff[Role.MANAGER]
    supplier_ids = _create_partners(rng, manager)
    context = SeedContext(rng, admin, staff, supplier_ids, _create_coffees(manager, supplier_ids),
                          _create_packaging(manager))  # fmt: skip
    _create_products(context)
    _create_customers(context)
    _set_opening_balances(admin, start)
    settings_service.update_settings(admin, {"default_shipping_box_id": str(context.packaging_ids["box_s"])})
    _set_opening_stock(context)
    return context
