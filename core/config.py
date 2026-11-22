import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILE = PROJECT_ROOT / ".streamlit" / "secrets.toml"


def load_secrets() -> Mapping[str, Any]:
    try:
        import streamlit as st
        from streamlit import runtime

        if runtime.exists():
            return st.secrets
    except ImportError:
        pass
    if SECRETS_FILE.exists():
        with SECRETS_FILE.open("rb") as file:
            return tomllib.load(file)
    return {}


def get_database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    try:
        return load_secrets()["database"]["url"]
    except KeyError as error:
        raise ConfigurationError(
            "Database URL not configured. Set DATABASE_URL or [database].url in .streamlit/secrets.toml."
        ) from error


def get_admin_emails() -> frozenset[str]:
    emails = load_secrets().get("app", {}).get("admin_emails", [])
    return frozenset(email.strip().lower() for email in emails)
