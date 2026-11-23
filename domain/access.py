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
    BACKDATE_OPERATIONS = "BACKDATE_OPERATIONS"
    MANAGE_CATALOG = "MANAGE_CATALOG"
    MANAGE_PRODUCTS = "MANAGE_PRODUCTS"
    MANAGE_PRICES = "MANAGE_PRICES"
    MANAGE_CUSTOMERS = "MANAGE_CUSTOMERS"
    MANAGE_SUPPLIERS = "MANAGE_SUPPLIERS"
    VIEW_FINANCE = "VIEW_FINANCE"
    MANAGE_FINANCE_SETUP = "MANAGE_FINANCE_SETUP"
    VIEW_PURCHASES = "VIEW_PURCHASES"
    MANAGE_PURCHASES = "MANAGE_PURCHASES"
    RECEIVE_PURCHASES = "RECEIVE_PURCHASES"
    CANCEL_PURCHASES = "CANCEL_PURCHASES"
    ADJUST_INVENTORY = "ADJUST_INVENTORY"
    VIEW_PRODUCTION = "VIEW_PRODUCTION"
    MANAGE_PRODUCTION = "MANAGE_PRODUCTION"
    VIEW_SALES = "VIEW_SALES"
    MANAGE_SALES = "MANAGE_SALES"
    CANCEL_SALES = "CANCEL_SALES"
    APPROVE_DISCOUNTS = "APPROVE_DISCOUNTS"
    VIEW_INTEGRITY = "VIEW_INTEGRITY"


ADMIN_ONLY_PERMISSIONS = frozenset({Permission.MANAGE_USERS, Permission.BACKDATE_OPERATIONS})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.MANAGER: frozenset(Permission) - ADMIN_ONLY_PERMISSIONS,
    Role.PRODUCTION: frozenset(
        {
            Permission.MANAGE_CATALOG,
            Permission.MANAGE_PRODUCTS,
            Permission.VIEW_PURCHASES,
            Permission.MANAGE_PURCHASES,
            Permission.RECEIVE_PURCHASES,
            Permission.VIEW_PRODUCTION,
            Permission.MANAGE_PRODUCTION,
        }
    ),
    Role.SALES: frozenset({Permission.MANAGE_CUSTOMERS, Permission.VIEW_SALES, Permission.MANAGE_SALES}),
    Role.FINANCE: frozenset(
        {
            Permission.MANAGE_SUPPLIERS,
            Permission.VIEW_FINANCE,
            Permission.MANAGE_FINANCE_SETUP,
            Permission.VIEW_PURCHASES,
            Permission.MANAGE_PURCHASES,
            Permission.VIEW_INTEGRITY,
        }
    ),
    Role.VIEWER: frozenset(
        {Permission.VIEW_FINANCE, Permission.VIEW_PURCHASES, Permission.VIEW_PRODUCTION, Permission.VIEW_SALES}
    ),
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
