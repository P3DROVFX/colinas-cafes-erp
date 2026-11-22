from dataclasses import dataclass
from enum import StrEnum

from core.errors import AccessDeniedError


class Role(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    PRODUCTION = "PRODUCTION"
    SALES = "SALES"
    FINANCE = "FINANCE"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    MANAGE_USERS = "MANAGE_USERS"
    MANAGE_CATALOG = "MANAGE_CATALOG"
    MANAGE_PRODUCTS = "MANAGE_PRODUCTS"
    MANAGE_PRICES = "MANAGE_PRICES"
    MANAGE_CUSTOMERS = "MANAGE_CUSTOMERS"
    MANAGE_SUPPLIERS = "MANAGE_SUPPLIERS"
    VIEW_FINANCE_SETUP = "VIEW_FINANCE_SETUP"
    MANAGE_FINANCE_SETUP = "MANAGE_FINANCE_SETUP"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.MANAGER: frozenset(Permission) - {Permission.MANAGE_USERS},
    Role.PRODUCTION: frozenset({Permission.MANAGE_CATALOG, Permission.MANAGE_PRODUCTS}),
    Role.SALES: frozenset({Permission.MANAGE_CUSTOMERS}),
    Role.FINANCE: frozenset(
        {Permission.MANAGE_SUPPLIERS, Permission.VIEW_FINANCE_SETUP, Permission.MANAGE_FINANCE_SETUP}
    ),
    Role.VIEWER: frozenset({Permission.VIEW_FINANCE_SETUP}),
}


@dataclass(frozen=True, slots=True)
class User:
    id: int
    email: str
    name: str
    role: Role
    is_active: bool


def has_permission(user: User, permission: Permission) -> bool:
    return user.is_active and permission in ROLE_PERMISSIONS[user.role]


def ensure_permission(user: User, permission: Permission) -> None:
    if not has_permission(user, permission):
        raise AccessDeniedError("Você não tem permissão para executar esta ação.")
