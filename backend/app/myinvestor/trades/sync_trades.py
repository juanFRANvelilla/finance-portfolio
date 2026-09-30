"""
Sincroniza confirmaciones de compra de MyInvestor hacia asset_transactions.

Uso (lanzamiento suelto, fuera de FastAPI):
    python -m app.myinvestor.trades.sync_trades
    python -m app.myinvestor.trades.sync_trades --profile local

STANDALONE_PROFILE decide el archivo de este script:
    server → backend/.env.server
    local  → backend/.env

La tarea programada dentro de FastAPI no entra por aquí. Usará el APP_PROFILE
con el que arrancó la API.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[3]

# Perfil solo para este lanzamiento manual. "server" lee .env.server.
STANDALONE_PROFILE = "server"


def _activate_standalone_profile(profile: str) -> Path:
    """Fija el entorno antes de importar la app.

    config.py y database.py eligen la base al importarse. load_dotenv con
    override pisa un DATABASE_URL que ya viniera de .env en el proceso.
    """
    normalized = profile.strip().lower()
    if normalized not in {"server", "local"}:
        raise SystemExit("El perfil debe ser 'server' o 'local'.")

    os.environ["APP_PROFILE"] = normalized
    env_path = BACKEND_ROOT / (".env.server" if normalized == "server" else ".env")
    if not env_path.is_file():
        raise SystemExit(f"No existe {env_path}")

    load_dotenv(dotenv_path=env_path, override=True)
    return env_path


def _print_result(result) -> None:
    print(f"\n{'=' * 52}")
    if not result.success:
        print(f"ERROR: {result.error}")
    print("PROCESO FINALIZADO")
    print(f"  Correos leídos         : {result.raw_emails_count}")
    print(f"  Candidatos             : {result.candidates}")
    print(f"  Insertados             : {result.inserted}")
    print(f"  Skipped (ya existían)  : {result.skipped_duplicate}")
    print(f"  Omitidos (no compra)   : {result.skipped_not_buy}")
    print(f"  Omitidos (sin parsear) : {result.skipped_unparsed}")
    print(f"  Omitidos (sin activo)  : {result.skipped_unknown_asset}")
    print(f"  Omitidos (divisa)      : {result.skipped_currency}")
    print(f"  Snapshot (grupos)      : {result.snapshot_groups_processed}")
    print(
        f"  Snapshot omit. (≠ mes) : {result.snapshot_fills_skipped_not_current_month} "
        "(operación fuera del mes natural actual)"
    )
    print(f"{'=' * 52}\n")
    for message in result.messages:
        print(message)


def main(*, dump_unparsed_bodies: bool = True) -> None:
    from app.services.myinvestor_sync_service import sync_myinvestor_transactions

    result = sync_myinvestor_transactions(dump_unparsed_bodies=dump_unparsed_bodies)
    _print_result(result)
    if not result.success:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincronizar compras de MyInvestor con PostgreSQL")
    parser.add_argument(
        "--profile",
        choices=("server", "local"),
        default=STANDALONE_PROFILE,
        help="server usa .env.server; local usa .env (default: %(default)s)",
    )
    parser.add_argument(
        "--no-dump-unparsed",
        action="store_true",
        help="no imprimir el cuerpo completo de correos que no se puedan parsear",
    )
    args = parser.parse_args()
    env_path = _activate_standalone_profile(args.profile)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from sqlalchemy.engine.url import make_url

    from app.core.config import get_settings

    db_url = make_url(get_settings().resolved_database_url)
    print(f"Entorno {env_path.name} → {db_url.host}:{db_url.port}/{db_url.database}")
    main(dump_unparsed_bodies=not args.no_dump_unparsed)
