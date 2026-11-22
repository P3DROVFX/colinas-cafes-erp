from typing import Any

from core.db import transaction
from core.errors import AccessDeniedError, BusinessRuleError
from domain.access import Permission, Role, User, ensure_permission
from repositories import users as users_repository


def sign_in(email: str, name: str, admin_emails: frozenset[str]) -> User:
    email = email.strip().lower()
    with transaction(email) as connection:
        user = users_repository.find_user_by_email(connection, email)
        if user is None:
            role = Role.ADMIN if email in admin_emails else Role.VIEWER
            user = users_repository.insert_user(connection, email, name or email, role)
        if not user.is_active:
            raise AccessDeniedError("Seu acesso está bloqueado. Procure o administrador do sistema.")
        users_repository.record_login(connection, user.id)
    return user


def get_active_user(email: str) -> User:
    with transaction(email) as connection:
        user = users_repository.find_user_by_email(connection, email)
    if user is None or not user.is_active:
        raise AccessDeniedError("Seu acesso está bloqueado. Procure o administrador do sistema.")
    return user


def list_users(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_USERS)
    with transaction(actor.email) as connection:
        return users_repository.list_users(connection)


def update_user_access(actor: User, user_id: int, role: Role, is_active: bool) -> None:
    ensure_permission(actor, Permission.MANAGE_USERS)
    with transaction(actor.email) as connection:
        target = users_repository.find_user_by_id_for_update(connection, user_id)
        if target is None:
            raise BusinessRuleError("Usuário não encontrado.")
        loses_admin = target.role is Role.ADMIN and target.is_active and (role is not Role.ADMIN or not is_active)
        if loses_admin and users_repository.count_active_admins(connection) <= 1:
            raise BusinessRuleError("Não é possível remover o último administrador ativo.")
        users_repository.update_user_access(connection, user_id, role, is_active)
