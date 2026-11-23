"""Generates the development history: python -m scripts.seed --profile full|small."""

import argparse
import os
import random
import sys
import time
from collections import Counter
from datetime import date, timedelta

from psycopg.conninfo import conninfo_to_dict

from core import db
from core.clock import business_day, today
from core.config import get_database_url
from scripts.seed import data
from scripts.seed.setup import ADMIN_EMAIL, create_master_data
from scripts.seed.simulation import simulate
from services.integrity import run_integrity_checks
from services.users import get_active_user

SAFE_SUFFIXES = ("_dev", "_test")


class SeedRefusedError(RuntimeError):
    pass


def profile_period(profile: str, end: date) -> tuple[date, date]:
    if profile == "small":
        return end - timedelta(days=data.SMALL_DAYS - 1), end
    return data.FULL_START, end


def ensure_safe_database(url: str, allow_production: bool) -> None:
    name = conninfo_to_dict(url).get("dbname", "")
    if not name.endswith(SAFE_SUFFIXES) and not allow_production:
        raise SeedRefusedError(
            f"O banco '{name}' não termina em _dev ou _test. Use --allow-production só se tiver certeza."
        )
    sales = db.fetch_one("SELECT count(*) AS total FROM sales")["total"]
    if sales:
        raise SeedRefusedError(f"O banco já tem {sales} vendas. O histórico só é gerado em banco vazio.")


def run_seed(profile: str, end: date | None = None) -> Counter:
    end = end or today() - timedelta(days=1)
    start, end = profile_period(profile, end)
    rng = random.Random(data.SEED_NUMBER)
    with business_day(start):
        context = create_master_data(rng, start)
    return simulate(context, start, end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera o histórico de operações da Colinas Cafés.")
    parser.add_argument("--profile", choices=("small", "full"), default="full")
    parser.add_argument("--database-url", help="Banco de destino (padrão: DATABASE_URL ou secrets).")
    parser.add_argument("--allow-production", action="store_true", help="Permite um banco sem sufixo _dev/_test.")
    args = parser.parse_args(argv)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    started = time.monotonic()
    try:
        ensure_safe_database(get_database_url(), args.allow_production)
    except SeedRefusedError as error:
        print(f"Seed recusado: {error}", file=sys.stderr)
        return 1
    stats = run_seed(args.profile)
    elapsed = time.monotonic() - started
    for label, count in sorted(stats.items()):
        print(f"{label:<40} {count:>6}")
    failed = [result.code for result in run_integrity_checks(get_active_user(ADMIN_EMAIL)) if not result.passed]
    print(f"Concluído em {elapsed:.0f} s. Integridade: {'OK' if not failed else 'falhas em ' + ', '.join(failed)}")
    db.close_pool()
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
