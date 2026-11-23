from typing import Any

from core.db import transaction
from core.errors import BusinessRuleError
from domain.access import Permission, User, ensure_permission
from domain.settings import SettingType, ensure_consistent_settings, normalize_setting
from repositories import audit as audit_repository
from repositories import settings as settings_repository
from repositories.sales import find_shipping_box

SHIPPING_BOX_KEY = "default_shipping_box_id"


def list_settings(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_SETTINGS)
    with transaction(actor.email) as connection:
        return settings_repository.list_settings(connection)


def update_settings(actor: User, changes: dict[str, str | None]) -> list[str]:
    """RF-ADM-02: validates type, range and consistency, then records every change in the audit log."""
    ensure_permission(actor, Permission.MANAGE_SETTINGS)
    with transaction(actor.email) as connection:
        current = {row["key"]: row for row in settings_repository.list_settings(connection)}
        normalized = {}
        for key, raw in changes.items():
            if key not in current:
                raise BusinessRuleError(f"Parâmetro desconhecido: {key}.")
            row = current[key]
            normalized[key] = normalize_setting(key, SettingType(row["value_type"]), raw, row["description"])
        merged = {key: row["value"] for key, row in current.items()} | normalized
        ensure_consistent_settings(merged)
        box_id = normalized.get(SHIPPING_BOX_KEY)
        if box_id is not None:
            box = find_shipping_box(connection, int(box_id))
            if box is None or box["id"] != int(box_id):
                raise BusinessRuleError("A caixa de envio padrão deve ser uma caixa de envio ativa.")
        changed = [key for key, value in normalized.items() if value != current[key]["value"]]
        for key in changed:
            settings_repository.update_setting(connection, key, normalized[key])
            audit_repository.insert_audit(
                connection, "settings", "UPDATE", {"key": key, "value": current[key]["value"]},
                {"key": key, "value": normalized[key]}, actor.email,
            )  # fmt: skip
    return changed


def list_settings_history(actor: User) -> list[dict[str, Any]]:
    ensure_permission(actor, Permission.MANAGE_SETTINGS)
    with transaction(actor.email) as connection:
        return audit_repository.list_audit(connection, "settings")
