"""
register-legacy-crypto-trades.py
---------------------------------
Sincroniza manualmente el historial de fills de KuCoin hacia asset_transactions.

Uso:
    cd backend/
    python -m app.kucoin.register-legacy-crypto-trades

Por defecto usa START_DATE fija (útil para re-importaciones históricas).
Para usar la fecha dinámica (MAX en BD), pasa --dynamic-start.

Requiere en .env: DATABASE_URL, KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

from app.core.database import SessionLocal
from app.repositories.asset_transactions import resolve_sync_start_datetime
from app.services.kucoin_sync_service import KucoinSyncResult, sync_kucoin_transactions

# Fecha fija para importaciones históricas manuales.
START_DATE = datetime(2025, 11, 20)


def _print_result(result: KucoinSyncResult) -> None:
    print(f"\n{'=' * 52}")
    if not result.success:
        print(f"ERROR: {result.error}")
    print("PROCESO FINALIZADO")
    print(f"  Rango                  : {result.start_date.date()} → {result.end_date.date()}")
    print(f"  Tasa USDT→EUR          : {result.usdt_eur_rate:.6f}")
    print(f"  Fills brutos           : {result.raw_fills_count}")
    print(f"  Candidatos procesados  : {result.candidates}")
    print(f"  Insertados             : {result.inserted}")
    print(f"  Skipped (ya existían)  : {result.skipped_duplicate}")
    print(f"  Omitidos (puente fiat) : {result.skipped_fiat_bridge}")
    print(f"  Omitidos (sin activo)  : {result.skipped_unknown_asset}")
    print(f"{'=' * 52}\n")
    for message in result.messages:
        print(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar fills de KuCoin con PostgreSQL")
    parser.add_argument(
        "--dynamic-start",
        action="store_true",
        help="Usar MAX(transaction_date) de la BD como fecha de inicio (igual que el scheduler)",
    )
    args = parser.parse_args()

    if args.dynamic_start:
        with SessionLocal() as db:
            start_date = resolve_sync_start_datetime(db)
        print(f"Fecha de inicio dinámica: {start_date.date()}")
    else:
        start_date = START_DATE
        print(f"Fecha de inicio fija: {start_date.date()}")

    result = sync_kucoin_transactions(start_date)
    _print_result(result)

    if not result.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
