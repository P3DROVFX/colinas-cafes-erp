from domain.access import Role
from domain.brazil import PersonType
from domain.catalog import Grind, PackagingKind, Process, RoastProfile
from domain.finance import AccountKind, DreGroup, EntryType
from domain.partners import Segment, SupplyType

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
