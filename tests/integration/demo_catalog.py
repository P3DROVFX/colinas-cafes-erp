from dataclasses import dataclass
from decimal import Decimal

from core.clock import today
from domain.access import User
from domain.brazil import PersonType
from domain.catalog import (
    FarmInput,
    GreenCoffeeInput,
    Grind,
    PackagingItemInput,
    PackagingKind,
    Process,
    ProductInput,
    RoastProfile,
)
from domain.inventory import StockItemKind
from domain.partners import SupplierInput, SupplyType
from domain.production import PackingInput, RoastBatchStatus, RoastInput
from domain.purchasing import PurchaseInput, PurchaseItemInput, PurchaseStatus
from services import catalog as catalog_service
from services import partners as partners_service
from services import production as production_service
from services import purchases as purchases_service
from services.production import PeriodFilters
from services.purchases import PurchaseFilters


@dataclass(frozen=True)
class DemoCatalog:
    coffee_supplier_id: int
    packaging_supplier_id: int
    coffee_id: int
    bag_id: int
    label_id: int
    box_id: int
    product_id: int

    def coffee_purchase(self, **changes) -> PurchaseInput:
        values = {
            "supplier_id": self.coffee_supplier_id,
            "items": (PurchaseItemInput(StockItemKind.GREEN_COFFEE, self.coffee_id, Decimal("30"), Decimal("60")),),
            "installments": 2,
            "first_due_days": 30,
        }
        return PurchaseInput(**(values | changes))

    def packaging_purchase(self) -> PurchaseInput:
        items = (
            PurchaseItemInput(StockItemKind.PACKAGING_ITEM, self.bag_id, Decimal("100"), Decimal("1.80")),
            PurchaseItemInput(StockItemKind.PACKAGING_ITEM, self.label_id, Decimal("100"), Decimal("0.35")),
            PurchaseItemInput(StockItemKind.PACKAGING_ITEM, self.box_id, Decimal("50"), Decimal("3.20")),
        )
        return PurchaseInput(self.packaging_supplier_id, items, installments=1, first_due_days=28)


def build_demo_catalog(manager: User) -> DemoCatalog:
    coffee_supplier_id = partners_service.create_supplier(
        manager, SupplierInput("Sítio Boa Vista", PersonType.INDIVIDUAL, "529.982.247-25", SupplyType.GREEN_COFFEE)
    )
    packaging_supplier_id = partners_service.create_supplier(
        manager, SupplierInput("EmbalaCafé Ltda", PersonType.COMPANY, "11.222.333/0001-81", SupplyType.PACKAGING)
    )
    farm_id = catalog_service.create_farm(
        manager,
        FarmInput("Sítio Boa Vista", "Taquaritinga do Norte", "PE", "José", False, coffee_supplier_id, 1000),
    )
    coffee_id = catalog_service.create_green_coffee(
        manager,
        GreenCoffeeInput(
            "BVCAT", "Boa Vista Catuaí Amarelo", farm_id, "Catuaí Amarelo", Process.NATURAL, 2026, Decimal("84.5")
        ),
    )
    packaging = [
        PackagingItemInput("Pacote valvulado 250 g", PackagingKind.BAG, 250),
        PackagingItemInput("Etiqueta padrão", PackagingKind.LABEL),
        PackagingItemInput("Caixa de envio P", PackagingKind.SHIPPING_BOX, 2000),
    ]
    bag_id, label_id, box_id = (catalog_service.create_packaging_item(manager, item) for item in packaging)
    product_id = catalog_service.create_product(manager, demo_product(coffee_id, bag_id, label_id))
    return DemoCatalog(coffee_supplier_id, packaging_supplier_id, coffee_id, bag_id, label_id, box_id, product_id)


def demo_product(
    coffee_id: int, bag_id: int, label_id: int, profile: RoastProfile = RoastProfile.MEDIUM
) -> ProductInput:
    return ProductInput(
        "Boa Vista Catuaí – Torra Média – Em grãos – 250 g",
        coffee_id,
        profile,
        Grind.WHOLE_BEAN,
        250,
        bag_id,
        label_id,
        Decimal("49.90"),
        Decimal("54.90"),
    )


def create_own_coffee(manager: User) -> int:
    farm_id = catalog_service.create_farm(
        manager, FarmInput("Fazenda Colinas", "Garanhuns", "PE", "Família Colinas", True, None, 900)
    )
    return catalog_service.create_green_coffee(
        manager,
        GreenCoffeeInput("COLBOU", "Colinas Bourbon Amarelo", farm_id, "Bourbon Amarelo", Process.NATURAL, 2026),
    )


def build_stocked_catalog(manager: User) -> DemoCatalog:
    """Demo steps 2 to 5: catalog, both purchases received, one roast and 20 bags packed."""
    catalog = build_demo_catalog(manager)
    for data in (catalog.coffee_purchase(), catalog.packaging_purchase()):
        purchases_service.create_purchase(manager, data)
    pending = PurchaseFilters(today(), today(), None, (PurchaseStatus.PENDING,))
    for purchase in purchases_service.list_purchases(manager, pending):
        purchases_service.receive_purchase(manager, purchase["id"])
    production_service.roast(manager, RoastInput(catalog.coffee_id, RoastProfile.MEDIUM, Decimal("10"), Decimal("8.4")))
    [batch] = production_service.list_roast_batches(manager, PeriodFilters(today(), today()), (RoastBatchStatus.OPEN,))
    production_service.pack(manager, PackingInput(catalog.product_id, batch["id"], 20))
    return catalog
