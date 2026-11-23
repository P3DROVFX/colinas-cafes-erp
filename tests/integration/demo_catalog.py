from dataclasses import dataclass
from decimal import Decimal

from domain.access import User
from domain.brazil import PersonType
from domain.catalog import FarmInput, GreenCoffeeInput, PackagingItemInput, PackagingKind, Process
from domain.inventory import StockItemKind
from domain.partners import SupplierInput, SupplyType
from domain.purchasing import PurchaseInput, PurchaseItemInput
from services import catalog as catalog_service
from services import partners as partners_service


@dataclass(frozen=True)
class DemoCatalog:
    coffee_supplier_id: int
    packaging_supplier_id: int
    coffee_id: int
    bag_id: int
    label_id: int
    box_id: int

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
    return DemoCatalog(coffee_supplier_id, packaging_supplier_id, coffee_id, bag_id, label_id, box_id)
