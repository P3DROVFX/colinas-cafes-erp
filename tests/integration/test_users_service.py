import pytest

from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Role
from services import users as users_service

ADMIN_EMAIL = "admin@colinas.com.br"
ADMIN_EMAILS = frozenset({ADMIN_EMAIL})


def test_configured_admin_email_signs_in_as_admin():
    user = users_service.sign_in("Admin@Colinas.com.br", "Admin", ADMIN_EMAILS)
    assert user.email == ADMIN_EMAIL
    assert user.role is Role.ADMIN


def test_unknown_email_signs_in_as_viewer():
    user = users_service.sign_in("visitante@gmail.com", "Visitante", ADMIN_EMAILS)
    assert user.role is Role.VIEWER


def test_sign_in_keeps_existing_role():
    admin = users_service.sign_in(ADMIN_EMAIL, "Admin", ADMIN_EMAILS)
    viewer = users_service.sign_in("gerente@gmail.com", "Gerente", ADMIN_EMAILS)
    users_service.update_user_access(admin, viewer.id, Role.MANAGER, True)
    assert users_service.sign_in("gerente@gmail.com", "Gerente", ADMIN_EMAILS).role is Role.MANAGER


def test_inactive_user_cannot_sign_in():
    admin = users_service.sign_in(ADMIN_EMAIL, "Admin", ADMIN_EMAILS)
    viewer = users_service.sign_in("bloqueado@gmail.com", "Bloqueado", ADMIN_EMAILS)
    users_service.update_user_access(admin, viewer.id, Role.VIEWER, False)
    with pytest.raises(AccessDeniedError):
        users_service.sign_in("bloqueado@gmail.com", "Bloqueado", ADMIN_EMAILS)


def test_viewer_cannot_change_access():
    users_service.sign_in(ADMIN_EMAIL, "Admin", ADMIN_EMAILS)
    viewer = users_service.sign_in("visitante@gmail.com", "Visitante", ADMIN_EMAILS)
    with pytest.raises(AccessDeniedError):
        users_service.update_user_access(viewer, viewer.id, Role.ADMIN, True)


def test_last_active_admin_cannot_be_demoted():
    admin = users_service.sign_in(ADMIN_EMAIL, "Admin", ADMIN_EMAILS)
    with pytest.raises(BusinessRuleError):
        users_service.update_user_access(admin, admin.id, Role.MANAGER, True)


def test_admin_can_be_demoted_when_another_admin_exists():
    admin = users_service.sign_in(ADMIN_EMAIL, "Admin", ADMIN_EMAILS)
    other = users_service.sign_in("socio@gmail.com", "Sócio", ADMIN_EMAILS)
    users_service.update_user_access(admin, other.id, Role.ADMIN, True)
    users_service.update_user_access(admin, admin.id, Role.MANAGER, True)
    assert users_service.get_active_user(ADMIN_EMAIL).role is Role.MANAGER
