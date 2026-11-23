"""Day-by-day simulation of the business (spec 13.4). Every operation goes through the service layer."""

import math
import random
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from core.clock import business_day
from core.errors import BusinessRuleError
from domain.access import Role
from domain.catalog import RoastProfile
from domain.dates import add_months
from domain.finance import EntryDisplayStatus, ManualEntryInput, SettlementInput, SettlementMethod
from domain.inventory import AdjustmentReason, StockItemKind, StockItemRef
from domain.numbers import round_kilograms, round_money
from domain.production import HarvestInput, PackingInput, RoastBatchStatus, RoastInput
from domain.purchasing import PurchaseInput, PurchaseItemInput, PurchaseStatus
from domain.sales import Channel, DeliveryType, PaymentMethod, SaleInput, SaleItemInput, ShipmentInput
from scripts.seed import data
from scripts.seed.setup import ProductState, SeedContext
from services import catalog as catalog_service
from services import finance as finance_service
from services import inventory as inventory_service
from services import production as production_service
from services import purchases as purchases_service
from services import sales as sales_service
from services.finance import EntryFilters
from services.inventory import AdjustmentInput
from services.production import PeriodFilters
from services.purchases import PurchaseFilters

MAX_ROASTS_PER_DAY = 2
ROAST_TEMPERATURES = {RoastProfile.LIGHT: (196, 204), RoastProfile.MEDIUM: (205, 212), RoastProfile.DARK: (214, 222)}
LOCAL_PAYMENTS = (
    (PaymentMethod.PIX, 45),
    (PaymentMethod.CASH, 15),
    (PaymentMethod.DEBIT_CARD, 20),
    (PaymentMethod.CREDIT_CARD, 20),
)


@dataclass
class PendingPurchase:
    id: int
    expected: date
    keys: frozenset[str]
    is_packaging: bool


@dataclass
class SimulationState:
    pending: list[PendingPurchase] = field(default_factory=list)
    to_ship: list[int] = field(default_factory=list)
    shipped: list[tuple[int, date]] = field(default_factory=list)
    to_deliver: list[int] = field(default_factory=list)
    quotes: list[int] = field(default_factory=list)
    reconciled_months: set[tuple[int, int]] = field(default_factory=set)
    shortage_ordered: bool = False
    old_crop_retired: bool = False
    shortage_delivered: bool = False
    stats: Counter = field(default_factory=Counter)


class Simulation:
    def __init__(self, context: SeedContext, start: date, end: date) -> None:
        self.context = context
        self.rng: random.Random = context.rng
        self.start = start
        self.end = end
        self.state = SimulationState()
        self.stock: dict[int, Decimal] = {}
        self.categories: dict[str, int] = {}
        self.addresses: dict[int, str] = {}
        self.bank_id = 0
        self.account_ids: list[int] = []

    def run(self) -> Counter:
        finance = self.context.user(Role.FINANCE)
        self.categories = {row["name"]: row["id"] for row in finance_service.get_entry_form_options(finance).categories}
        accounts = finance_service.list_account_balances(finance)
        self.bank_id = next(row["id"] for row in accounts if row["kind"] == "BANK")
        self.account_ids = [row["id"] for row in accounts]
        customers = sales_service.get_customer_options(self.context.user(Role.SALES))
        self.addresses = {
            row["id"]: ", ".join(part for part in (row["address"], row["city"], row["state"]) if part)
            for row in customers
            if row["address"]
        }
        day = self.start
        while day <= self.end:
            with business_day(day):
                self._run_day(day)
            day += timedelta(days=1)
        return self.state.stats

    def _run_day(self, day: date) -> None:
        self._monthly_entries(day)
        if day == data.PRICE_INCREASE_DATE:
            self._raise_prices()
        if day.weekday() == 6:
            return
        self._receive_purchases(day)
        self._harvest(day)
        self._reorder(day)
        self._ship_and_deliver(day)
        self._confirm_quotes()
        self._pack()
        self._close_residues(day)
        self._retire_sold_out_crop(day)
        self._roast(day)
        self._sell(day)
        self._settle(day)
        self._adjust(day)
        self._reconcile(day)

    def _attempt(self, label: str, action) -> Any:
        try:
            result = action()
        except BusinessRuleError:
            self.state.stats[f"{label} recusada"] += 1
            return None
        self.state.stats[label] += 1
        return result

    def _weighted(self, options: list[tuple[Any, int]]) -> Any:
        return self.rng.choices([option for option, _ in options], weights=[weight for _, weight in options])[0]

    def _poisson(self, mean: Decimal) -> int:
        limit, count, product = math.exp(-float(mean)), 0, self.rng.random()
        while product > limit:
            count += 1
            product *= self.rng.random()
        return count

    def _create_entry(self, label: str, category: str, description: str, amount: Decimal, due: date) -> None:
        finance = self.context.user(Role.FINANCE)
        entry = ManualEntryInput(self.categories[category], description, amount, due)
        self._attempt(label, lambda: finance_service.create_manual_entry(finance, entry))

    def _monthly_entries(self, day: date) -> None:
        if day.day == 1 or day == self.start:
            for expense in data.MONTHLY_EXPENSES:
                due = day.replace(day=expense.due_day)
                description = f"{expense.description} – {day:%m/%Y}"
                amount = Decimal(self.rng.randint(*expense.amount_range))
                self._create_entry(
                    "Despesa fixa", expense.category, description, amount, due if due >= day else add_months(due, 1)
                )
        for when, category, description, amount, due_days in data.ONE_OFF_ENTRIES:
            if when == day:
                self._create_entry("Lançamento avulso", category, description, amount, day + timedelta(days=due_days))

    def _raise_prices(self) -> None:
        manager = self.context.user(Role.MANAGER)
        for product in self.context.products:
            current = product.sku_input

            def bump(price: Decimal | None) -> Decimal | None:
                return None if price is None else math.ceil(price * data.PRICE_INCREASE_FACTOR) - Decimal("0.10")

            product.sku_input = replace(
                current,
                price_local=bump(current.price_local),
                price_online=bump(current.price_online),
                price_wholesale=bump(current.price_wholesale),
            )
            catalog_service.update_product(manager, product.id, product.sku_input)
        self.state.stats["Reajuste de preços"] += 1

    def _receive_purchases(self, day: date) -> None:
        production = self.context.user(Role.PRODUCTION)
        for pending in list(self.state.pending):
            if day >= pending.expected and self._attempt(
                "Compra recebida", lambda p=pending: purchases_service.receive_purchase(production, p.id)
            ):
                self.state.pending.remove(pending)

    def _shortage_blocks(self, key: str, stock: Decimal, day: date) -> bool:
        """C4: the bag supplier stops taking orders; once the bag runs out, the late order arrives days later."""
        start, end = data.SHORTAGE_BLOCK
        if key != data.SHORTAGE_ITEM or not start <= day <= end or self.state.shortage_ordered:
            return False
        if stock > 0:
            return True
        self.state.shortage_ordered = True
        return False

    def _harvest(self, day: date) -> None:
        for when, kilograms in data.HARVESTS:
            if when == day:
                cost = round_money(kilograms * data.HARVEST_COST_PER_KG * Decimal(str(self.rng.uniform(0.95, 1.08))))
                harvest = HarvestInput(
                    self.context.coffee_ids["COLBOU"],
                    kilograms,
                    cost,
                    self.context.supplier_ids["beneficia"],
                    day + timedelta(days=21),
                    "Colheita seletiva, secagem em terreiro suspenso",
                )
                self._attempt(
                    "Colheita",
                    lambda h=harvest: production_service.register_harvest(self.context.user(Role.PRODUCTION), h),
                )

    def _positions(self, kind: StockItemKind) -> dict[int, Decimal]:
        rows = inventory_service.list_stock_positions(self.context.user(Role.MANAGER), kind)
        return {row["id"]: row["stock"] for row in rows}

    def _create_purchase(
        self,
        supplier_key: str,
        items: tuple[PurchaseItemInput, ...],
        keys: frozenset[str],
        is_packaging: bool,
        day: date,
        installments: int,
        lead_days: int | None = None,
    ) -> None:
        manager = self.context.user(Role.MANAGER)
        supplier = next(item for item in data.SUPPLIERS if item.key == supplier_key)
        expected = day + timedelta(days=lead_days or supplier.lead_time_days + self.rng.randint(-1, 2))
        freight = Decimal(self.rng.choice((0, 60, 90, 120))) if not is_packaging else Decimal("45")
        purchase = PurchaseInput(
            self.context.supplier_ids[supplier_key], items, freight, installments, 28 if is_packaging else 30, expected
        )
        number = self._attempt("Compra", lambda: purchases_service.create_purchase(manager, purchase))
        if number is None:
            return
        filters = PurchaseFilters(day, day, self.context.supplier_ids[supplier_key], (PurchaseStatus.PENDING,))
        purchase_id = next(
            row["id"] for row in purchases_service.list_purchases(manager, filters) if row["number"] == number
        )
        self.state.pending.append(PendingPurchase(purchase_id, expected, keys, is_packaging))

    def _reorder(self, day: date) -> None:
        coffees = self._positions(StockItemKind.GREEN_COFFEE)
        pending_keys = {key for pending in self.state.pending for key in pending.keys}
        for coffee in data.COFFEES:
            if coffee.code in data.NO_REORDER or coffee.code in pending_keys:
                continue
            if coffee.available_from and day < coffee.available_from:
                continue
            if coffees[self.context.coffee_ids[coffee.code]] >= Decimal("35"):
                continue
            new_crop = coffee.available_from is not None or day >= data.NEW_CROP_DATE
            cost = coffee.base_cost * (data.NEW_CROP_PRICE_FACTOR if new_crop and coffee.code != "CDGEI" else 1)
            quantity = Decimal(self.rng.randint(*coffee.lot_kg) // 10 * 10)
            item = PurchaseItemInput(
                StockItemKind.GREEN_COFFEE, self.context.coffee_ids[coffee.code], quantity, round_money(cost)
            )
            supplier = next(farm.supplier for farm in data.FARMS if farm.key == coffee.farm)
            self._create_purchase(supplier, (item,), frozenset({coffee.code}), False, day, 2 if quantity > 50 else 1)
        packaging = self._positions(StockItemKind.PACKAGING_ITEM)
        order = []
        for item in data.PACKAGING:
            stock = packaging[self.context.packaging_ids[item.key]]
            if item.key in pending_keys or stock >= item.reorder_point or self._shortage_blocks(item.key, stock, day):
                continue
            order.append(item)
        if not order:
            return
        items = tuple(
            PurchaseItemInput(
                StockItemKind.PACKAGING_ITEM,
                self.context.packaging_ids[item.key],
                Decimal(item.order_quantity),
                item.cost,
            )
            for item in order
        )
        late = self.state.shortage_ordered and any(item.key == data.SHORTAGE_ITEM for item in order)
        lead_days = data.SHORTAGE_DAYS if late and not self.state.shortage_delivered else None
        self.state.shortage_delivered = self.state.shortage_delivered or late
        self._create_purchase("embala", items, frozenset(item.key for item in order), True, day, 1, lead_days)

    def _ship_and_deliver(self, day: date) -> None:
        seller = self.context.user(Role.SALES)
        for sale_id in self.state.to_ship:
            detail = sales_service.get_sale_detail(seller, sale_id)
            if detail.sale["status"] != "CONFIRMED":
                continue
            boxes = detail.sale["box_count"]
            cost = round_money(Decimal(str(13 + 5 * boxes + self.rng.uniform(-3, 9))))
            tracking = f"BR{self.rng.randint(100000000, 999999999)}"
            carrier = self._weighted([("Correios", 6), ("Jadlog", 3), ("Loggi", 2)])
            if self._attempt(
                "Expedição",
                lambda s=sale_id, t=tracking, c=cost, r=carrier: sales_service.ship_sale(
                    seller, s, ShipmentInput(t, c, r)
                ),
            ):
                self.state.shipped.append((sale_id, day))
        self.state.to_ship = []
        for sale_id, shipped_on in list(self.state.shipped):
            if (day - shipped_on).days >= self.rng.randint(2, 5):
                self._attempt("Entrega", lambda s=sale_id: sales_service.deliver_sale(seller, s))
                self.state.shipped.remove((sale_id, shipped_on))
        for sale_id in self.state.to_deliver:
            self._attempt("Entrega", lambda s=sale_id: sales_service.deliver_sale(seller, s))
        self.state.to_deliver = []

    def _confirm_quotes(self) -> None:
        seller = self.context.user(Role.SALES)
        for sale_id in self.state.quotes:
            if self.rng.random() < 0.5:
                result = self._attempt("Orçamento confirmado", lambda s=sale_id: sales_service.confirm_sale(seller, s))
                if result is not None:
                    self._track_delivery(
                        result.sale_id,
                        DeliveryType(sales_service.get_sale_detail(seller, result.sale_id).sale["delivery_type"]),
                    )
        self.state.quotes = []

    def _pack(self) -> None:
        production = self.context.user(Role.PRODUCTION)
        stocks = self._positions(StockItemKind.PRODUCT)
        for product in sorted(self.context.products, key=lambda item: -item.seed.popularity):
            missing = product.seed.target - int(stocks.get(product.id, 0))
            if missing < product.seed.target / 2:
                continue
            batches = [
                batch
                for batch in production_service.list_compatible_batches(production, product.id)
                if batch["days_since_roast"] >= 1
            ]
            if not batches:
                continue
            materials = production_service.get_packing_materials(production, product.id)
            bags, labels = int(materials.bag.stock), int(materials.label.stock)
            for batch in batches:
                fits = int(batch["stock_kg"] * 1000 // product.seed.weight_g)
                count = min(missing, fits, bags, labels)
                if count <= 0:
                    continue
                if self._attempt(
                    "Envase",
                    lambda b=batch, n=count, p=product.id: production_service.pack(
                        production, PackingInput(p, b["id"], n)
                    ),
                ):
                    missing, bags, labels = missing - count, bags - count, labels - count

    def _close_residues(self, day: date) -> None:
        """RF-EST-05: leftovers smaller than the smallest bag of the family are written off."""
        production = self.context.user(Role.PRODUCTION)
        smallest: dict[tuple[int, str], Decimal] = {}
        for product in self.context.products:
            key = (product.coffee_id, product.seed.profile.value)
            smallest[key] = min(smallest.get(key, Decimal("99")), Decimal(product.seed.weight_g) / 1000)
        batches = production_service.list_roast_batches(
            production, PeriodFilters(self.start - timedelta(days=30), day), (RoastBatchStatus.OPEN,)
        )
        for batch in batches:
            if 0 < batch["stock_kg"] < smallest.get((batch["green_coffee_id"], batch["roast_profile"]), Decimal("99")):
                self._attempt(
                    "Lote encerrado",
                    lambda b=batch: production_service.close_roast_batch(
                        production, b["id"], "Sobra menor que o menor pacote"
                    ),
                )

    def _retire_sold_out_crop(self, day: date) -> None:
        """The 2025 crop is sold out once the new one arrives; its products leave the catalog."""
        if day < data.NEW_CROP_DATE or self.state.old_crop_retired:
            return
        old = [item for item in self.context.products if item.seed.coffee in data.NO_REORDER - {"COLBOU"}]
        coffee_id = self.context.coffee_ids["BVCAT25"]
        stocks = self._positions(StockItemKind.PRODUCT)
        if self._positions(StockItemKind.GREEN_COFFEE)[coffee_id] > 0 or any(stocks.get(item.id, 0) for item in old):
            return
        manager = self.context.user(Role.MANAGER)
        for item in old:
            catalog_service.set_product_active(manager, item.id, False)
            self.context.products.remove(item)
        catalog_service.set_green_coffee_active(manager, coffee_id, False)
        self.state.old_crop_retired = True
        self.state.stats["Safra antiga retirada do catálogo"] += 1

    def _roast(self, day: date) -> None:
        production = self.context.user(Role.PRODUCTION)
        stocks = self._positions(StockItemKind.PRODUCT)
        greens = self._positions(StockItemKind.GREEN_COFFEE)
        open_batches = production_service.list_roast_batches(
            production, PeriodFilters(self.start - timedelta(days=30), day), (RoastBatchStatus.OPEN,)
        )
        families: dict[tuple[int, RoastProfile], list[ProductState]] = {}
        for product in self.context.products:
            families.setdefault((product.coffee_id, product.seed.profile), []).append(product)
        plans = []
        for (coffee_id, profile), products in families.items():
            if greens[coffee_id] < Decimal("4"):
                continue
            target = sum(Decimal(item.seed.target * item.seed.weight_g) / 1000 for item in products)
            batch_kg = sum(
                (
                    batch["stock_kg"]
                    for batch in open_batches
                    if batch["green_coffee_id"] == coffee_id and batch["roast_profile"] == profile
                ),
                Decimal("0"),
            )
            packed_kg = sum(stocks.get(item.id, 0) * item.seed.weight_g / Decimal(1000) for item in products)
            coverage = (batch_kg + packed_kg) / target
            forced = day in data.FRESHNESS_OVERROAST_DAYS and self.context.coffee_code(coffee_id) == "CDCAT"
            if coverage < Decimal("0.7") or forced:
                needed_green = (target * Decimal("1.3") - batch_kg - packed_kg) / Decimal("0.84")
                size = Decimal("12") if forced else min(max(needed_green, Decimal("5")), Decimal("15"))
                plans.append((Decimal("-1") if forced else coverage, coffee_id, profile, size))
        for _, coffee_id, profile, size in sorted(plans)[:MAX_ROASTS_PER_DAY]:
            green = min(
                (size + self.rng.randint(-1, 1)).quantize(Decimal("1")), greens[coffee_id].quantize(Decimal("1"))
            )
            green = min(max(green, Decimal("1")), Decimal("15"))
            low, high = data.WEIGHT_LOSS_RANGES[profile]
            loss = Decimal(str(self.rng.uniform(float(low), float(high))))
            if self.context.coffee_code(coffee_id) == data.ANOMALOUS_COFFEE and profile is RoastProfile.MEDIUM:
                loss += data.ANOMALY_EXTRA_LOSS
            roasted = round_kilograms(green * (1 - loss / 100))
            temperature = Decimal(self.rng.randint(*ROAST_TEMPERATURES[profile]))
            roast = RoastInput(
                coffee_id,
                profile,
                green,
                roasted,
                True,
                Decimal(self.rng.randint(9, 14)),
                temperature,
                "Torrefação – torrador 15 kg",
            )
            if self._attempt("Torra", lambda r=roast: production_service.roast(production, r)):
                greens[coffee_id] -= green

    def _seasonal_mean(self, channel: Channel, day: date) -> Decimal:
        mean = data.SALES_PER_DAY[channel.value] * data.MONTH_FACTORS.get(day.month, Decimal("1"))
        if channel is Channel.ONLINE:
            months = (day.year - data.FULL_START.year) * 12 + day.month - data.FULL_START.month
            mean *= (1 + data.ONLINE_MONTHLY_GROWTH) ** max(months, 0)
            if day.month == data.FATHERS_DAY_MONTH and day.day <= 9:
                mean *= data.FATHERS_DAY_ONLINE_FACTOR
            if data.BLACK_FRIDAY_WARMUP[0] <= day <= data.BLACK_FRIDAY_WARMUP[1]:
                mean *= data.BLACK_FRIDAY_ONLINE_FACTOR
        return mean

    def _pick_items(self, candidates: list[ProductState], lines: int, quantities: tuple[int, int]) -> tuple:
        items, used = [], set()
        for _ in range(lines):
            available = [
                item for item in candidates if item.id not in used and self.stock.get(item.id, 0) >= quantities[0]
            ]
            if not available:
                break
            product = self._weighted([(item, item.seed.popularity) for item in available])
            quantity = min(self.rng.randint(*quantities), int(self.stock[product.id]))
            used.add(product.id)
            items.append(SaleItemInput(product.id, quantity))
        return tuple(items)

    def _amount(self, items: tuple[SaleItemInput, ...], channel: Channel) -> Decimal:
        prices = {item.id: item.sku_input for item in self.context.products}
        field_name = {
            Channel.LOCAL: "price_local",
            Channel.ONLINE: "price_online",
            Channel.WHOLESALE: "price_wholesale",
        }
        return sum(
            (getattr(prices[item.product_id], field_name[channel]) * item.quantity for item in items), Decimal("0")
        )

    def _customer_address(self, customer_id: int) -> str:
        return self.addresses[customer_id]

    def _local_order(self) -> SaleInput | None:
        retail = [item for item in self.context.products if item.seed.weight_g <= 500]
        items = self._pick_items(
            retail, 1 if self.rng.random() < 0.75 else 2, (1, 2) if self.rng.random() < 0.15 else (1, 1)
        )
        if not items:
            return None
        delivery = DeliveryType.PICKUP if self.rng.random() < 0.88 else DeliveryType.LOCAL_DELIVERY
        customer = self.context.walk_in_id
        if delivery is DeliveryType.LOCAL_DELIVERY or self.rng.random() < 0.3:
            customer = self.rng.choice(self.context.consumer_ids)
        freight = Decimal("8") if delivery is DeliveryType.LOCAL_DELIVERY else Decimal("0")
        address = self._customer_address(customer) if delivery is DeliveryType.LOCAL_DELIVERY else None
        return SaleInput(
            customer,
            Channel.LOCAL,
            delivery,
            self._weighted(list(LOCAL_PAYMENTS)),
            items,
            freight_amount=freight,
            delivery_address=address,
        )

    def _online_order(self) -> SaleInput | None:
        lines = self._weighted([(1, 50), (2, 35), (3, 15)])
        items = self._pick_items(self.context.products, lines, (1, 2))
        if not items:
            return None
        customer = self.rng.choice(self.context.consumer_ids)
        amount = self._amount(items, Channel.ONLINE)
        weight = sum(
            next(p.seed.weight_g for p in self.context.products if p.id == item.product_id) * item.quantity
            for item in items
        )
        freight = Decimal("0")
        if amount < data.FREE_SHIPPING_FROM:
            freight = next(price for limit, price in data.SHIPPING_PRICES if weight <= limit)
        discount = round_money(amount * Decimal("0.10")) if self.rng.random() < 0.08 else Decimal("0")
        payment = PaymentMethod.PIX if self.rng.random() < 0.4 else PaymentMethod.CREDIT_CARD
        return SaleInput(
            customer,
            Channel.ONLINE,
            DeliveryType.SHIPPING,
            payment,
            items,
            discount,
            freight,
            self._customer_address(customer),
        )

    def _wholesale_order(self, company: str | None = None) -> SaleInput | None:
        weights = [(item.name, item.weight) for item in data.COMPANIES]
        company = company or self._weighted(weights)
        big = company in (data.COMPANIES[0].name, data.COMPANIES[1].name)
        bulk = [item for item in self.context.products if item.seed.price_wholesale]
        target_kg = self.rng.randint(6, 9) if big else self.rng.randint(5, 6)
        lines = self._weighted([(1, 40), (2, 45), (3, 15)])
        items = self._pick_items(bulk, lines, (max(2, target_kg // lines), max(2, target_kg // lines) + 1))
        if not items or sum(item.quantity for item in items) < 5:
            return None
        customer_id = self.context.company_ids[company]
        shipping = self.rng.random() < 0.3
        payment = (
            PaymentMethod.BANK_SLIP
            if self.rng.random() < 0.8 or company == data.DEFAULTED_CUSTOMER
            else PaymentMethod.PIX
        )
        discount = (
            round_money(self._amount(items, Channel.WHOLESALE) * Decimal("0.05"))
            if self.rng.random() < 0.3
            else Decimal("0")
        )
        return SaleInput(
            customer_id,
            Channel.WHOLESALE,
            DeliveryType.SHIPPING if shipping else DeliveryType.LOCAL_DELIVERY,
            payment,
            items,
            discount,
            Decimal("35") if shipping else Decimal("0"),
            self._customer_address(customer_id),
        )

    def _track_delivery(self, sale_id: int, delivery: DeliveryType) -> None:
        if delivery is DeliveryType.SHIPPING:
            self.state.to_ship.append(sale_id)
        elif delivery is DeliveryType.LOCAL_DELIVERY:
            self.state.to_deliver.append(sale_id)

    def _place(self, order: SaleInput | None, as_quote: bool = False) -> None:
        if order is None:
            self.state.stats["Venda perdida por falta de estoque"] += 1
            return
        seller = self.context.user(Role.SALES)
        if as_quote:
            result = self._attempt("Orçamento", lambda: sales_service.create_sale(seller, order))
            if result:
                self.state.quotes.append(result.sale_id)
            return
        pickup = order.delivery_type is DeliveryType.PICKUP
        will_cancel = order.channel is Channel.LOCAL and pickup and self.rng.random() < 0.012
        try:
            result = sales_service.create_sale(seller, order, confirm=True, deliver_now=pickup and not will_cancel)
        except BusinessRuleError as error:
            if order.payment_method is not PaymentMethod.BANK_SLIP:
                self.state.stats["Venda recusada"] += 1
                return
            self.state.stats["Boleto bloqueado (RN-20)" if "vencido" in str(error) else "Venda recusada"] += 1
            result = self._attempt(
                "Venda",
                lambda: sales_service.create_sale(
                    seller, replace(order, payment_method=PaymentMethod.PIX), confirm=True
                ),
            )
            if result is None:
                return
        else:
            self.state.stats["Venda"] += 1
        for item in order.items:
            self.stock[item.product_id] -= item.quantity
        self._track_delivery(result.sale_id, order.delivery_type)
        if will_cancel:
            self._attempt(
                "Venda cancelada",
                lambda: sales_service.cancel_sale(
                    self.context.user(Role.MANAGER), result.sale_id, "Cliente desistiu no caixa"
                ),
            )

    def _sell(self, day: date) -> None:
        self.stock = self._positions(StockItemKind.PRODUCT)
        if day in (date(2026, 9, 1), date(2026, 9, 22)):
            self._place(self._wholesale_order(data.DEFAULTED_CUSTOMER))
        builders = {
            Channel.LOCAL: self._local_order,
            Channel.ONLINE: self._online_order,
            Channel.WHOLESALE: self._wholesale_order,
        }
        for channel, build in builders.items():
            for _ in range(self._poisson(self._seasonal_mean(channel, day))):
                as_quote = channel is not Channel.LOCAL and self.rng.random() < 0.05
                self._place(build(), as_quote)

    def _settle(self, day: date) -> None:
        finance = self.context.user(Role.FINANCE)
        filters = EntryFilters(
            day - timedelta(days=400), day, None, (EntryDisplayStatus.PENDING, EntryDisplayStatus.OVERDUE)
        )
        ids = tuple(
            row["id"]
            for row in finance_service.list_entries(finance, filters)
            if not (
                row["counterparty"] == data.DEFAULTED_CUSTOMER
                and row["entry_type"] == "RECEIVABLE"
                and data.DEFAULT_WINDOW[0] <= row["due_date"] <= data.DEFAULT_WINDOW[1]
            )
        )
        if ids:
            self._attempt(
                "Liquidação em lote",
                lambda: finance_service.settle_entries(
                    finance, SettlementInput(ids, self.bank_id, SettlementMethod.TRANSFER, day)
                ),
            )

    def _adjust(self, day: date) -> None:
        manager = self.context.user(Role.MANAGER)
        if day.weekday() == 5 and day.isocalendar().week % 2 == 0:
            stocks = self._positions(StockItemKind.PRODUCT)
            candidates = [
                item for item in self.context.products if stocks.get(item.id, 0) > 3 and item.seed.weight_g == 250
            ]
            if candidates:
                product = self._weighted([(item, item.seed.popularity) for item in candidates])
                self._attempt(
                    "Ajuste",
                    lambda: inventory_service.adjust_inventory(
                        manager,
                        AdjustmentInput(
                            StockItemRef(StockItemKind.PRODUCT, product.id),
                            AdjustmentReason.TASTING,
                            "Degustação de sábado na loja",
                            lost_quantity=Decimal("1"),
                        ),
                    ),
                )
        is_last_business_day = (day + timedelta(days=1)).month != day.month or (
            day.weekday() == 5 and (day + timedelta(days=2)).month != day.month
        )
        if is_last_business_day:
            label_id = self.context.packaging_ids["label"]
            current = self._positions(StockItemKind.PACKAGING_ITEM)[label_id]
            counted = max(current - self.rng.randint(2, 6), Decimal("0"))
            if counted != current:
                self._attempt(
                    "Ajuste",
                    lambda: inventory_service.adjust_inventory(
                        manager,
                        AdjustmentInput(
                            StockItemRef(StockItemKind.PACKAGING_ITEM, label_id),
                            AdjustmentReason.COUNT,
                            "Inventário mensal das etiquetas",
                            counted_stock=counted,
                        ),
                    ),
                )
        if day.day == 15:
            greens = self._positions(StockItemKind.GREEN_COFFEE)
            coffee_id = max(greens, key=greens.get)
            if greens[coffee_id] > 10:
                self._attempt(
                    "Ajuste",
                    lambda: inventory_service.adjust_inventory(
                        manager,
                        AdjustmentInput(
                            StockItemRef(StockItemKind.GREEN_COFFEE, coffee_id),
                            AdjustmentReason.DAMAGE,
                            "Saca rasgada na movimentação do armazém",
                            lost_quantity=Decimal("1"),
                        ),
                    ),
                )

    def _reconcile(self, day: date) -> None:
        if day.day < 5 or (day.year, day.month) in self.state.reconciled_months:
            return
        self.state.reconciled_months.add((day.year, day.month))
        finance = self.context.user(Role.FINANCE)
        last_month_end = day.replace(day=1) - timedelta(days=1)
        if last_month_end < self.start:
            return
        for account_id in self.account_ids:
            entries = finance_service.list_reconciliation(finance, account_id, self.start, last_month_end)
            ids = [row["id"] for row in entries if not row["is_reconciled"]]
            if ids:
                self._attempt("Conciliação", lambda i=ids: finance_service.set_reconciled(finance, i, True, day))


def simulate(context: SeedContext, start: date, end: date) -> Counter:
    return Simulation(context, start, end).run()
