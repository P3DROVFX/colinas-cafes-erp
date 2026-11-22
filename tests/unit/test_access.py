import pytest

from core.errors import AccessDeniedError
from domain.access import Permission, Role, User, ensure_permission, has_permission


def make_user(role: Role, is_active: bool = True) -> User:
    return User(id=1, email="pessoa@example.com", name="Pessoa", role=role, is_active=is_active)


def test_admin_can_manage_users():
    assert has_permission(make_user(Role.ADMIN), Permission.MANAGE_USERS)


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.ADMIN])
def test_non_admin_roles_cannot_manage_users(role):
    assert not has_permission(make_user(role), Permission.MANAGE_USERS)


def test_inactive_user_has_no_permissions():
    assert not has_permission(make_user(Role.ADMIN, is_active=False), Permission.MANAGE_USERS)


def test_ensure_permission_raises_for_missing_permission():
    with pytest.raises(AccessDeniedError):
        ensure_permission(make_user(Role.VIEWER), Permission.MANAGE_USERS)


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (Role.MANAGER, Permission.MANAGE_PRICES, True),
        (Role.PRODUCTION, Permission.MANAGE_CATALOG, True),
        (Role.PRODUCTION, Permission.MANAGE_PRODUCTS, True),
        (Role.PRODUCTION, Permission.MANAGE_PRICES, False),
        (Role.PRODUCTION, Permission.VIEW_FINANCE_SETUP, False),
        (Role.SALES, Permission.MANAGE_CUSTOMERS, True),
        (Role.SALES, Permission.MANAGE_SUPPLIERS, False),
        (Role.FINANCE, Permission.MANAGE_SUPPLIERS, True),
        (Role.FINANCE, Permission.MANAGE_FINANCE_SETUP, True),
        (Role.FINANCE, Permission.MANAGE_CATALOG, False),
        (Role.VIEWER, Permission.VIEW_FINANCE_SETUP, True),
        (Role.VIEWER, Permission.MANAGE_CUSTOMERS, False),
    ],
)
def test_master_data_permissions_follow_role_matrix(role, permission, allowed):
    assert has_permission(make_user(role), permission) is allowed
