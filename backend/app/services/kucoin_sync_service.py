"""Sincronización de fills de KuCoin hacia asset_transactions y asset_sales."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

import ccxt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.repositories.asset_sales import upsert_kucoin_daily_asset_sale
from app.services.kucoin_daily_asset_sales import build_daily_kucoin_sale_row
from app.repositories.asset_transactions import (
    insert_transactions_batch,
    load_kucoin_asset_name_map,
    resolve_sync_start_datetime,
    sum_position_by_asset_type_ids,
)
from app.services.monthly_asset_snapshot import apply_transactions_to_monthly_snapshot

logger = logging.getLogger(__name__)

USDT_EUR_FALLBACK_RATE = 0.8535
WEEK_WINDOW_DAYS = 6
KUCOIN_PAGE_SLEEP_SECONDS = 0.3


@dataclass
class KucoinSyncResult:
    start_date: datetime
    end_date: datetime
    raw_fills_count: int = 0
    usdt_eur_rate: float = 0.0
    candidates: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    sales_candidates: int = 0
    sales_inserted: int = 0
    sales_skipped_duplicate: int = 0
    skipped_fiat_bridge: int = 0
    skipped_unknown_asset: int = 0
    skipped_invalid_sell: int = 0
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def get_sync_start_datetime(db: Session | None = None) -> datetime:
    """Resuelve la fecha de inicio dinámica (MAX en BD o fallback)."""
    if db is not None:
        return resolve_sync_start_datetime(db)
    with SessionLocal() as session:
        return resolve_sync_start_datetime(session)


def sync_kucoin_transactions(start_date: datetime) -> KucoinSyncResult:
    """Extrae fills de KuCoin desde `start_date` e inserta compras/ventas."""
    end_date = datetime.now()
    result = KucoinSyncResult(start_date=start_date, end_date=end_date)

    try:
        raw_fills = _fetch_kucoin_fills(start_date, end_date)
        result.raw_fills_count = len(raw_fills)

        if not raw_fills:
            result.messages.append("No se encontraron fills en el rango consultado.")
            logger.info("KuCoin sync: 0 fills entre %s y %s", start_date.date(), end_date.date())
            return result

        usdt_eur_rate = _calculate_usdt_eur_rate(raw_fills)
        result.usdt_eur_rate = usdt_eur_rate

        with SessionLocal() as db:
            asset_map = load_kucoin_asset_name_map(db)
            if not asset_map:
                result.success = False
                result.error = "No hay activos KuCoin (price_source='kucoin') en asset_types."
                logger.error(result.error)
                return result

            position_totals = sum_position_by_asset_type_ids(db, list(asset_map.values()))
            fills, daily_sale_keys, stats = _transform_fills(
                raw_fills,
                asset_map,
                usdt_eur_rate,
                position_totals,
            )
            result.candidates = len([f for f in fills if f["asset_amount"] > 0])
            result.sales_candidates = len(daily_sale_keys)
            result.skipped_fiat_bridge = stats["skipped_fiat_bridge"]
            result.skipped_unknown_asset = stats["skipped_unknown_asset"]
            result.skipped_invalid_sell = stats["skipped_invalid_sell"]

            if not fills:
                result.messages.append("No hay operaciones válidas para insertar.")
                return result

            inserted, skipped, inserted_fills = insert_transactions_batch(db, fills)
            result.inserted = inserted
            result.skipped_duplicate = skipped

            upserted_sale_keys: set[tuple[str, date]] = set()
            if daily_sale_keys:
                upserted = 0
                for asset_type_id, sale_date in sorted(
                    daily_sale_keys, key=lambda item: (item[1], item[0])
                ):
                    daily_row = build_daily_kucoin_sale_row(db, asset_type_id, sale_date)
                    if daily_row is None:
                        continue
                    upsert_kucoin_daily_asset_sale(db, daily_row)
                    upserted_sale_keys.add((asset_type_id, sale_date))
                    upserted += 1
                db.commit()
                result.sales_inserted = upserted

            snapshot_fills: list[dict] = []
            for fill in inserted_fills:
                if Decimal(str(fill["asset_amount"])) < 0:
                    sale_key = (fill["asset_type_id"], fill["transaction_date"])
                    if sale_key not in upserted_sale_keys:
                        continue
                snapshot_fills.append(fill)

            if snapshot_fills:
                apply_transactions_to_monthly_snapshot(db, snapshot_fills)

        logger.info(
            "KuCoin sync OK: %s tx insertadas, %s ventas insertadas, %s duplicados (desde %s)",
            result.inserted,
            result.sales_inserted,
            result.skipped_duplicate + result.sales_skipped_duplicate,
            start_date.date(),
        )
        return result

    except Exception as exc:
        result.success = False
        result.error = str(exc)
        logger.exception("KuCoin sync falló: %s", exc)
        return result


def run_scheduled_kucoin_sync() -> KucoinSyncResult:
    """Ejecuta la sincronización usando la fecha de inicio dinámica desde BD."""
    start_date = get_sync_start_datetime()
    logger.info(
        "Sync KuCoin: consultando fills desde %s (fecha MAX en BD o fallback 2025-11-20)",
        start_date.date(),
    )
    return sync_kucoin_transactions(start_date)


def _kucoin_credentials() -> tuple[str, str, str]:
    settings = get_settings()
    api_key = settings.kucoin_api_key
    secret = settings.kucoin_secret
    passphrase = settings.kucoin_passphrase

    if not api_key or not secret or not passphrase:
        raise ValueError(
            "Faltan credenciales de KuCoin. Define KUCOIN_API_KEY, KUCOIN_SECRET y KUCOIN_PASSPHRASE."
        )
    return api_key, secret, passphrase


def _fetch_kucoin_fills(start_date: datetime, end_date: datetime) -> list[dict]:
    api_key, secret, passphrase = _kucoin_credentials()

    exchange = ccxt.kucoin(
        {
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,
            "enableRateLimit": True,
            "timeout": 10_000,
        }
    )

    all_fills: list[dict] = []
    current_start = start_date

    logger.info("Escaneando KuCoin: %s → %s", start_date.date(), end_date.date())

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=WEEK_WINDOW_DAYS), end_date)
        start_ms = int(current_start.timestamp() * 1000)
        end_ms = int(current_end.timestamp() * 1000)

        try:
            response = exchange.private_get_fills(
                {"startAt": start_ms, "endAt": end_ms, "pageSize": 100}
            )
            items = response.get("data", {}).get("items", [])
            if items:
                all_fills.extend(items)
        except Exception as exc:
            logger.warning(
                "Error en ventana KuCoin %s → %s: %s: %s",
                current_start.date(),
                current_end.date(),
                type(exc).__name__,
                exc,
            )

        current_start = current_end + timedelta(seconds=1)
        time.sleep(KUCOIN_PAGE_SLEEP_SECONDS)

    logger.info("Total fills brutos extraídos: %s", len(all_fills))
    return all_fills


def _calculate_usdt_eur_rate(raw_fills: list[dict]) -> float:
    total_eur_spent = 0.0
    total_usdt_received = 0.0

    for fill in raw_fills:
        symbol = fill.get("symbol", "")
        side = fill.get("side", "").upper()
        if symbol.upper() == "USDT-EUR" and side == "BUY":
            total_eur_spent += float(fill.get("funds", 0))
            total_usdt_received += float(fill.get("size", 0))

    if total_usdt_received > 0:
        rate = total_eur_spent / total_usdt_received
        logger.info(
            "Tasa USDT→EUR desde fills: %.6f (%.2f EUR / %.2f USDT)",
            rate,
            total_eur_spent,
            total_usdt_received,
        )
        return rate

    logger.info("Sin operaciones USDT-EUR; usando fallback %.4f", USDT_EUR_FALLBACK_RATE)
    return USDT_EUR_FALLBACK_RATE


def _quote_to_native_amount(funds: float, quote_currency: str, usdt_eur_rate: float) -> float | None:
    if quote_currency == "EUR":
        return funds
    if quote_currency == "USDT":
        return funds * usdt_eur_rate
    return None


def _transform_fills(
    raw_fills: list[dict],
    asset_map: dict[str, str],
    usdt_eur_rate: float,
    position_totals: dict[str, tuple[Decimal, Decimal]],
) -> tuple[list[dict], set[tuple[str, date]], dict[str, int]]:
    parsed: list[dict] = []
    skipped_fiat_bridge = 0
    skipped_unknown_asset = 0
    skipped_invalid_sell = 0

    for fill in raw_fills:
        symbol = fill.get("symbol", "")
        side = fill.get("side", "").upper()
        if side not in {"BUY", "SELL"}:
            continue

        parts = symbol.upper().split("-")
        if len(parts) != 2:
            logger.warning("Símbolo con formato inesperado: %s", symbol)
            continue

        base_currency, quote_currency = parts

        if base_currency == "USDT":
            skipped_fiat_bridge += 1
            continue

        asset_type_id = asset_map.get(base_currency)
        if asset_type_id is None:
            logger.warning("Activo '%s' (par %s) no encontrado en asset_types", base_currency, symbol)
            skipped_unknown_asset += 1
            continue

        exchange_trade_id = fill.get("tradeId") or fill.get("id")
        if not exchange_trade_id:
            logger.warning("Fill sin tradeId/id para %s", symbol)
            skipped_unknown_asset += 1
            continue

        created_at_ms = int(fill.get("createdAt", 0))
        executed_at = datetime.utcfromtimestamp(created_at_ms / 1000)
        transaction_date = executed_at.date()
        funds = float(fill.get("funds", 0))
        size = float(fill.get("size", 0))
        fee = float(fill.get("fee", 0))

        native_amount = _quote_to_native_amount(funds, quote_currency, usdt_eur_rate)
        if native_amount is None:
            logger.warning("Divisa de cotización desconocida '%s' en %s", quote_currency, symbol)
            skipped_unknown_asset += 1
            continue

        if size <= 0:
            skipped_unknown_asset += 1
            continue

        execution_price = native_amount / size
        parsed.append(
            {
                "side": side,
                "symbol": symbol,
                "exchange_trade_id": str(exchange_trade_id),
                "asset_type_id": asset_type_id,
                "transaction_date": transaction_date,
                "executed_at": executed_at,
                "native_amount": Decimal(str(round(native_amount, 8))),
                "size": Decimal(str(size)),
                "execution_price": Decimal(str(round(execution_price, 8))),
                "fee_amount": Decimal(str(fee)),
            }
        )

    parsed.sort(key=lambda item: item["executed_at"])

    running: dict[str, tuple[Decimal, Decimal]] = {
        asset_id: (Decimal(str(units)), Decimal(str(invested)))
        for asset_id, (units, invested) in position_totals.items()
    }

    tx_rows: list[dict] = []
    daily_sale_keys: set[tuple[str, date]] = set()

    for item in parsed:
        asset_type_id = item["asset_type_id"]
        units_before, invested_before = running.get(asset_type_id, (Decimal("0"), Decimal("0")))

        if item["side"] == "BUY":
            tx_rows.append(
                {
                    "symbol": item["symbol"],
                    "exchange_trade_id": item["exchange_trade_id"],
                    "asset_type_id": asset_type_id,
                    "transaction_date": item["transaction_date"],
                    "invested_amount": item["native_amount"],
                    "asset_amount": item["size"],
                    "execution_price": item["execution_price"],
                    "fee_amount": item["fee_amount"],
                }
            )
            running[asset_type_id] = (
                units_before + item["size"],
                invested_before + item["native_amount"],
            )
            continue

        # SELL
        if units_before <= 0:
            logger.warning(
                "Venta KuCoin omitida (sin posición previa): trade=%s asset=%s",
                item["exchange_trade_id"],
                item["symbol"],
            )
            skipped_invalid_sell += 1
            continue

        sold_units = item["size"]
        avg_buy_price = (
            (invested_before / units_before).quantize(Decimal("0.0001"))
            if units_before > 0
            else Decimal("0")
        )

        tx_rows.append(
            {
                "symbol": item["symbol"],
                "exchange_trade_id": item["exchange_trade_id"],
                "asset_type_id": asset_type_id,
                "transaction_date": item["transaction_date"],
                "invested_amount": None,
                "asset_amount": -sold_units,
                "execution_price": item["execution_price"],
                "fee_amount": item["fee_amount"],
            }
        )

        daily_sale_keys.add((asset_type_id, item["transaction_date"]))

        cost_removed = avg_buy_price * sold_units
        running[asset_type_id] = (
            units_before - sold_units,
            invested_before - cost_removed,
        )

    stats = {
        "skipped_fiat_bridge": skipped_fiat_bridge,
        "skipped_unknown_asset": skipped_unknown_asset,
        "skipped_invalid_sell": skipped_invalid_sell,
    }
    return tx_rows, daily_sale_keys, stats
