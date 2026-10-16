"""
Importación puntual MyInvestor (PDF Inversis) → asset_transactions.

Solo compras y ventas; dividendos ignorados. Ventas: unidades negativas e
`invested_amount` negativo (coste PMP), igual que KuCoin/MyInvestor IMAP.

Uso (desde backend/):
    pip install pypdf   # one-off

    # Pre (misma BD que ./run.sh pre → .env.server):
    python -m scripts.myinvestor_pdf_import.import_transactions \\
        --profile pre --ticker MSF.DE --dry-run

    # Local (.env):
    python -m scripts.myinvestor_pdf_import.import_transactions \\
        --ticker MSF.DE

    También: APP_PROFILE=server python -m scripts.myinvestor_pdf_import.import_transactions ...

PyCharm (Run current file):
    Working directory = backend/
    En Run Configuration → Parameters, por ejemplo:
        --profile pre --ticker MSF.DE --dry-run -v
    O sin Parameters, variables de entorno:
        APP_PROFILE=server  MYINVESTOR_PDF_TICKER=MSF.DE  MYINVESTOR_PDF_DRY_RUN=1
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from scripts.myinvestor_pdf_import.bootstrap_env import BACKEND_ROOT, bootstrap_backend_env

_APP_PROFILE, _ENV_PATH = bootstrap_backend_env()

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.myinvestor_sync_service import MYINVESTOR_ID_ALIASES
from app.services.transaction_pmp import negative_invested_for_sell
from app.repositories.asset_transactions import (
    insert_transactions_batch,
    load_asset_match_index,
    sum_position_by_asset_type_ids,
)
from scripts.myinvestor_pdf_import.parse_inversis_pdf import (
    InversisTradeRow,
    _TRADE_ROW_RE,
    extract_text_from_pdf,
    parse_inversis_pdf,
)

logger = logging.getLogger(__name__)
MONEY_QUANT = Decimal("0.00000001")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT)


def _pdf_lookup_keys(ticker: str) -> set[str]:
    """Claves para emparejar nombre de PDF con --ticker (ticker, ISIN, alias MyInvestor)."""
    upper = ticker.strip().upper()
    keys = {upper, upper.replace(".", ""), upper.replace(".", "_")}
    for isin, alias in MYINVESTOR_ID_ALIASES.items():
        if alias.upper() == upper:
            keys.add(isin.upper())
        if isin.upper() == upper:
            keys.add(alias.upper())
    return keys


def _pdf_matches_ticker(path: Path, keys: set[str]) -> bool:
    stem = path.stem.upper()
    stem_flat = stem.replace(".", "").replace("_", "")
    for key in keys:
        ku = key.upper()
        kf = ku.replace(".", "").replace("_", "")
        if stem == ku or ku in stem or stem in ku or kf in stem_flat or stem_flat in kf:
            return True
    return False


def _resolve_asset(ticker: str, db) -> tuple[str, str]:
    index = load_asset_match_index(db)
    key = ticker.strip().upper()
    match = index.get(key)
    if match is None:
        raise SystemExit(
            f"No hay asset_types con ticker/name {key!r}. "
            "Créalo antes de importar."
        )
    return match.asset_type_id, match.currency.upper()


def _collect_pdf_rows(
    pdf_dir: Path, ticker: str, *, verbose: bool = False
) -> list[InversisTradeRow]:
    if not pdf_dir.is_dir():
        raise SystemExit(f"Directorio inexistente: {pdf_dir}")

    ticker_upper = ticker.upper()
    lookup_keys = _pdf_lookup_keys(ticker_upper)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No hay PDF en {pdf_dir}")

    preferred = pdf_dir / f"{ticker_upper}.pdf"
    if preferred.is_file():
        targets = [preferred]
    else:
        targets = [p for p in pdfs if _pdf_matches_ticker(p, lookup_keys)]
        if not targets:
            names = ", ".join(p.name for p in pdfs)
            raise SystemExit(
                f"No se encontró {preferred.name} ni PDF emparejado con {ticker_upper!r} "
                f"(claves: {', '.join(sorted(lookup_keys))}). Encontrados: {names}"
            )

    if verbose:
        print(f"[verbose] pdf-dir: {pdf_dir.resolve()}")
        print(f"[verbose] PDF en carpeta: {', '.join(p.name for p in pdfs)}")
        print(f"[verbose] Archivos a parsear: {', '.join(p.name for p in targets)}")

    by_transaccion: dict[str, InversisTradeRow] = {}
    for pdf_path in targets:
        parsed = parse_inversis_pdf(pdf_path)
        if verbose:
            print(f"[verbose] {pdf_path.name}: {len(parsed)} fila(s) COMPRA/VENTA")
            for row in parsed:
                print(
                    f"  id={row.transaccion} {row.side} {row.transaction_date} "
                    f"units={row.units} net={row.net_amount} {row.currency}"
                )
        if not parsed and verbose:
            text = extract_text_from_pdf(pdf_path).replace("\xa0", " ")
            matches = len(list(_TRADE_ROW_RE.finditer(text)))
            sample = next(
                (
                    line.strip()
                    for line in text.splitlines()
                    if ("COMPRA" in line or "VENTA" in line)
                    and re.search(r"\d{2}/\d{2}/\d{4}\d{2}/\d{2}/\d{4}\d+", line)
                ),
                None,
            )
            print(f"[verbose] regex matches en texto: {matches}")
            if sample:
                print(f"[verbose] línea ejemplo: {sample!r}")

        for row in parsed:
            by_transaccion.setdefault(row.transaccion, row)

    rows = list(by_transaccion.values())
    rows.sort(key=lambda row: (row.transaction_date, row.transaccion))
    return rows


def _build_fills(
    rows: list[InversisTradeRow],
    asset_type_id: str,
    asset_currency: str,
    position_totals: dict[str, tuple[Decimal, Decimal]],
) -> tuple[list[dict], int]:
    """Misma semántica que `_transform_fills` en kucoin_sync_service (compras/ventas)."""
    skipped_invalid_sell = 0
    running: dict[str, tuple[Decimal, Decimal]] = {
        asset_type_id: position_totals.get(asset_type_id, (Decimal("0"), Decimal("0")))
    }
    fills: list[dict] = []

    for row in rows:
        if row.currency != asset_currency:
            raise SystemExit(
                f"Transacción {row.transaccion}: divisa {row.currency} "
                f"≠ divisa del activo ({asset_currency})"
            )

        units_before, invested_before = running.get(
            asset_type_id, (Decimal("0"), Decimal("0"))
        )

        if row.side == "COMPRA":
            if row.units <= 0:
                continue
            invested = _quantize(row.net_amount)
            price = _quantize(row.net_price)
            fills.append(
                {
                    "exchange_trade_id": row.transaccion,
                    "asset_type_id": asset_type_id,
                    "transaction_date": row.transaction_date,
                    "invested_amount": invested,
                    "asset_amount": row.units,
                    "execution_price": price,
                    "fee_amount": Decimal("0"),
                }
            )
            running[asset_type_id] = (
                units_before + row.units,
                invested_before + invested,
            )
            continue

        if row.side == "VENTA":
            if row.units <= 0:
                continue
            if units_before <= 0:
                logger.warning(
                    "Venta omitida (sin posición previa): transaccion=%s fecha=%s",
                    row.transaccion,
                    row.transaction_date,
                )
                skipped_invalid_sell += 1
                continue

            sold_units = row.units
            _, invested_out = negative_invested_for_sell(
                units_before=units_before,
                invested_before=invested_before,
                sold_units=sold_units,
            )
            cost_removed = -invested_out

            fills.append(
                {
                    "exchange_trade_id": row.transaccion,
                    "asset_type_id": asset_type_id,
                    "transaction_date": row.transaction_date,
                    "invested_amount": invested_out,
                    "asset_amount": -sold_units,
                    "execution_price": _quantize(row.net_price),
                    "fee_amount": Decimal("0"),
                }
            )
            running[asset_type_id] = (
                units_before - sold_units,
                invested_before - cost_removed,
            )

    return fills, skipped_invalid_sell


def _mask_database_url(url: str) -> str:
    return re.sub(r":([^:@/]+)@", ":***@", url)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Importar operaciones MyInvestor (PDF Inversis) a asset_transactions"
    )
    parser.add_argument(
        "--profile",
        "-p",
        choices=("local", "pre", "server"),
        default=None,
        help="Entorno: pre/server → .env.server; local → .env (default: APP_PROFILE o local)",
    )
    parser.add_argument(
        "--ticker",
        default=os.environ.get("MYINVESTOR_PDF_TICKER"),
        help="Ticker en asset_types (ej. MSF.DE). Alternativa: env MYINVESTOR_PDF_TICKER",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=BACKEND_ROOT / "scripts" / "myinvestor_pdf_import" / "pdfs",
        help="Carpeta con PDF exportados",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostrar filas sin insertar",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Detalle de PDFs parseados (útil si salen 0 operaciones)",
    )
    args = parser.parse_args()
    if not args.ticker:
        parser.error(
            "Falta --ticker (ej. MSF.DE). En PyCharm: Run → Edit Configurations → "
            "Parameters: --profile pre --ticker MSF.DE --dry-run "
            "o env MYINVESTOR_PDF_TICKER=MSF.DE"
        )
    if os.environ.get("MYINVESTOR_PDF_DRY_RUN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        args.dry_run = True
    if os.environ.get("MYINVESTOR_PDF_VERBOSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        args.verbose = True

    settings = get_settings()
    print(
        f"Perfil: {_APP_PROFILE} ({_ENV_PATH.name}) → "
        f"{_mask_database_url(settings.resolved_database_url)}"
    )

    rows = _collect_pdf_rows(args.pdf_dir, args.ticker, verbose=args.verbose)
    print(f"PDF: {len(rows)} operaciones COMPRA/VENTA (sin dividendos)")

    with SessionLocal() as db:
        asset_type_id, asset_currency = _resolve_asset(args.ticker, db)
        position_totals = sum_position_by_asset_type_ids(db, [asset_type_id])
        fills, skipped_sells = _build_fills(
            rows, asset_type_id, asset_currency, position_totals
        )

    print(f"Candidatos a insertar: {len(fills)}")
    if skipped_sells:
        print(f"Ventas omitidas (sin posición): {skipped_sells}")

    executed_at = datetime.now()
    for fill in fills:
        fill["executed_at"] = executed_at

    print(f"executed_at (todas las filas): {executed_at.isoformat(sep=' ', timespec='seconds')}")

    for fill in fills:
        side = "COMPRA" if fill["asset_amount"] > 0 else "VENTA"
        print(
            f"  transaction_date={fill['transaction_date']} {side} "
            f"id={fill['exchange_trade_id']} "
            f"units={fill['asset_amount']} invested={fill['invested_amount']} "
            f"price={fill['execution_price']}"
        )

    if args.dry_run:
        print("\n(dry-run: no se escribió en la BD)")
        return

    if not fills:
        print("Nada que insertar.")
        return

    with SessionLocal() as db:
        inserted, skipped, _ = insert_transactions_batch(db, fills)
    print(f"\nInsertados: {inserted}, omitidos por exchange_trade_id duplicado: {skipped}")


if __name__ == "__main__":
    # Run as script file (PyCharm): asegurar que backend/ está en sys.path
    _backend = Path(__file__).resolve().parents[2]
    if str(_backend) not in sys.path:
        sys.path.insert(0, str(_backend))
    main()
