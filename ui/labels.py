from domain.access import Role
from domain.brazil import PersonType
from domain.catalog import Grind, PackagingKind, Process, RoastProfile
from domain.finance import AccountKind, DreGroup, EntryDisplayStatus, EntryType
from domain.inventory import AdjustmentReason, MovementType, SourceModule, StockItemKind, StockStatus
from domain.partners import Segment, SupplyType
from domain.production import RoastBatchStatus
from domain.purchasing import PurchaseStatus
from domain.sales import Channel, DeliveryType, PaymentMethod, SaleDisplayStatus

ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Administrador",
    Role.MANAGER: "Gerente",
    Role.PRODUCTION: "Produção",
    Role.SALES: "Comercial",
    Role.FINANCE: "Financeiro",
    Role.VIEWER: "Visitante",
}

PERSON_TYPE_LABELS: dict[PersonType, str] = {
    PersonType.INDIVIDUAL: "Pessoa física",
    PersonType.COMPANY: "Pessoa jurídica",
}

SUPPLY_TYPE_LABELS: dict[SupplyType, str] = {
    SupplyType.GREEN_COFFEE: "Café verde",
    SupplyType.PACKAGING: "Embalagens",
    SupplyType.SERVICE: "Serviços",
}

SEGMENT_LABELS: dict[Segment, str] = {
    Segment.CONSUMER: "Consumidor",
    Segment.COFFEE_SHOP: "Cafeteria",
    Segment.RESTAURANT: "Restaurante",
    Segment.EMPORIUM: "Empório",
    Segment.COMPANY: "Empresa",
}

PROCESS_LABELS: dict[Process, str] = {
    Process.NATURAL: "Natural",
    Process.PULPED_NATURAL: "Cereja descascado",
    Process.WASHED: "Lavado",
    Process.FERMENTED: "Fermentado",
}

PACKAGING_KIND_LABELS: dict[PackagingKind, str] = {
    PackagingKind.BAG: "Pacote",
    PackagingKind.LABEL: "Etiqueta",
    PackagingKind.SHIPPING_BOX: "Caixa de envio",
}

ROAST_PROFILE_LABELS: dict[RoastProfile, str] = {
    RoastProfile.LIGHT: "Clara",
    RoastProfile.MEDIUM: "Média",
    RoastProfile.DARK: "Escura",
}

GRIND_LABELS: dict[Grind, str] = {
    Grind.WHOLE_BEAN: "Em grãos",
    Grind.ESPRESSO: "Fina (espresso)",
    Grind.FILTER: "Média (coado)",
    Grind.FRENCH_PRESS: "Grossa (prensa)",
}

ENTRY_TYPE_LABELS: dict[EntryType, str] = {
    EntryType.PAYABLE: "A pagar",
    EntryType.RECEIVABLE: "A receber",
}

DRE_GROUP_LABELS: dict[DreGroup, str] = {
    DreGroup.REVENUE: "Receita de vendas",
    DreGroup.OTHER_REVENUE: "Outras receitas",
    DreGroup.REFUND: "Reembolsos (só caixa)",
    DreGroup.INVENTORY: "Compras para estoque",
    DreGroup.SELLING_COST: "Custos de venda",
    DreGroup.OPERATING_EXPENSE: "Despesas operacionais",
}

ACCOUNT_KIND_LABELS: dict[AccountKind, str] = {
    AccountKind.CASH: "Caixa",
    AccountKind.BANK: "Banco",
}

ACTIVE_LABELS: dict[bool, str] = {True: "Ativo", False: "Inativo"}


BadgeStyle = tuple[str, str, str]

PURCHASE_STATUS_BADGES: dict[PurchaseStatus, BadgeStyle] = {
    PurchaseStatus.PENDING: ("Pendente", "blue", ":material/schedule:"),
    PurchaseStatus.RECEIVED: ("Recebida", "green", ":material/check_circle:"),
    PurchaseStatus.CANCELLED: ("Cancelada", "gray", ":material/block:"),
    PurchaseStatus.REVERSED: ("Estornada", "gray", ":material/undo:"),
}

ENTRY_STATUS_BADGES: dict[EntryDisplayStatus, BadgeStyle] = {
    EntryDisplayStatus.PENDING: ("Pendente", "blue", ":material/schedule:"),
    EntryDisplayStatus.OVERDUE: ("Vencido", "red", ":material/error:"),
    EntryDisplayStatus.SETTLED: ("Liquidado", "green", ":material/check_circle:"),
    EntryDisplayStatus.CANCELLED: ("Cancelado", "gray", ":material/block:"),
}

STOCK_ITEM_KIND_LABELS: dict[StockItemKind, str] = {
    StockItemKind.GREEN_COFFEE: "Cafés verdes",
    StockItemKind.ROAST_BATCH: "Lotes torrados",
    StockItemKind.PACKAGING_ITEM: "Embalagens",
    StockItemKind.PRODUCT: "Produtos",
}

MOVEMENT_TYPE_LABELS: dict[MovementType, str] = {
    MovementType.PURCHASE_IN: "Entrada por compra",
    MovementType.PURCHASE_REVERSAL: "Estorno de compra",
    MovementType.HARVEST_IN: "Entrada por colheita",
    MovementType.ROAST_OUT: "Saída para torra",
    MovementType.ROAST_IN: "Entrada da torra",
    MovementType.PACKING_OUT: "Saída para envase",
    MovementType.PACKING_IN: "Entrada do envase",
    MovementType.SALE_OUT: "Saída por venda",
    MovementType.SALE_REVERSAL: "Estorno de venda",
    MovementType.INVENTORY_ADJUSTMENT: "Ajuste de inventário",
}

ADJUSTMENT_REASON_LABELS: dict[AdjustmentReason, str] = {
    AdjustmentReason.COUNT: "Contagem",
    AdjustmentReason.LOSS: "Perda",
    AdjustmentReason.DAMAGE: "Avaria",
    AdjustmentReason.TASTING: "Degustação",
    AdjustmentReason.EXPIRED: "Vencimento",
    AdjustmentReason.OPENING: "Implantação de saldo",
}

SOURCE_MODULE_LABELS: dict[SourceModule, str] = {
    SourceModule.PURCHASES: "Compras",
    SourceModule.PRODUCTION: "Produção",
    SourceModule.SALES: "Vendas",
    SourceModule.INVENTORY: "Estoque",
    SourceModule.MANUAL: "Manual",
}

STOCK_STATUS_LABELS: dict[StockStatus, str] = {
    StockStatus.OK: "OK",
    StockStatus.BELOW_MINIMUM: "Abaixo do mínimo",
    StockStatus.EMPTY: "Zerado",
}

ROAST_BATCH_STATUS_BADGES: dict[RoastBatchStatus, BadgeStyle] = {
    RoastBatchStatus.OPEN: ("Aberto", "orange", ":material/local_fire_department:"),
    RoastBatchStatus.CLOSED: ("Encerrado", "gray", ":material/inventory:"),
}

CHANNEL_LABELS: dict[Channel, str] = {
    Channel.LOCAL: "Loja",
    Channel.ONLINE: "Online",
    Channel.WHOLESALE: "Atacado",
}

DELIVERY_TYPE_LABELS: dict[DeliveryType, str] = {
    DeliveryType.PICKUP: "Retirada na loja",
    DeliveryType.LOCAL_DELIVERY: "Entrega local",
    DeliveryType.SHIPPING: "Envio",
}

PAYMENT_METHOD_LABELS: dict[PaymentMethod, str] = {
    PaymentMethod.PIX: "PIX",
    PaymentMethod.CASH: "Dinheiro",
    PaymentMethod.DEBIT_CARD: "Cartão de débito",
    PaymentMethod.CREDIT_CARD: "Cartão de crédito",
    PaymentMethod.BANK_SLIP: "Boleto a prazo",
}

SALE_STATUS_BADGES: dict[SaleDisplayStatus, BadgeStyle] = {
    SaleDisplayStatus.QUOTE: ("Orçamento", "blue", ":material/request_quote:"),
    SaleDisplayStatus.EXPIRED: ("Orçamento expirado", "orange", ":material/timer_off:"),
    SaleDisplayStatus.CONFIRMED: ("Confirmada", "violet", ":material/check:"),
    SaleDisplayStatus.SHIPPED: ("Expedida", "orange", ":material/local_shipping:"),
    SaleDisplayStatus.DELIVERED: ("Entregue", "green", ":material/check_circle:"),
    SaleDisplayStatus.CANCELLED: ("Cancelada", "gray", ":material/block:"),
}
