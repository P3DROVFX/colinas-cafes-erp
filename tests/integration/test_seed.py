from datetime import timedelta

import pytest

from core.clock import today
from core.db import fetch_one
from scripts.seed.__main__ import SeedRefusedError, ensure_safe_database, run_seed
from scripts.seed.setup import ADMIN_EMAIL
from services.integrity import run_integrity_checks
from services.users import get_active_user


def test_small_seed_builds_consistent_history(database_url):
    stats = run_seed("small", today() - timedelta(days=1))
    assert stats["Venda"] > 30
    assert stats["Torra"] > 0 and stats["Envase"] > 0
    assert all(result.passed for result in run_integrity_checks(get_active_user(ADMIN_EMAIL)))
    assert fetch_one("SELECT max(sale_date) AS last FROM sales")["last"] < today()
    with pytest.raises(SeedRefusedError, match="já tem"):
        ensure_safe_database(database_url, allow_production=False)


def test_seed_refuses_databases_without_safe_suffix(database_url):
    with pytest.raises(SeedRefusedError, match="não termina em _dev ou _test"):
        ensure_safe_database("postgresql://user:secret@db.example.com:5432/postgres", allow_production=False)
