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


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.MANAGER: frozenset(),
    Role.PRODUCTION: frozenset(),
    Role.SALES: frozenset(),
    Role.FINANCE: frozenset(),
    Role.VIEWER: frozenset(),
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
