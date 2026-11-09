"""Importa el CSV de movimientos de Trade Republic.

Solo entran filas TRADING de tipo BUY o SELL. El activo se busca por nombre y
tiene que pertenecer a la entidad Trade Republic. Una venta sin ese activo no
hace nada. Una compra lo crea (ticker = symbol, divisa EUR o USD) aunque el
mismo nombre exista en otra entidad. Cada transaction_id se importa una vez. Si ese activo ya tiene el mismo tipo
de operación ese día, la fila del CSV se omite; el tipo contrario sí entra.
Después se registra la operación, la venta si es SELL y el líquido de la entidad.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.asset_transaction import AssetTransaction
from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.repositories.asset_sales import upsert_kucoin_daily_asset_sale
from app.repositories.asset_transactions import (
    insert_transactions_batch,
    load_exchange_trade_ids_with_prefix,
    sum_position_by_asset_type_ids,
)
from app.services.hybrid_entity_auto_adjust import apply_auto_trades_to_hybrid_entities
from app.services.monthly_asset_snapshot import apply_transactions_to_monthly_snapshot
from app.services.purchase_asset_type import (
    create_trade_republic_asset,
    find_asset_by_name_and_entity,
)
from app.services.transaction_pmp import negative_invested_for_sell

logger = logging.getLogger(__name__)

TRADE_ID_PREFIX = "traderepublic:"
_MONEY = Decimal("0.00000001")
_CURRENCY = {
    "EUR": "EUR",
    "EURO": "EUR",
    "USD": "USD",
    "DOLAR": "USD",
    "DOLLAR": "USD",
}


@dataclass(frozen=True)
class TradeRepublicTrade:
    transaction_id: str
    side: str
    name: str
    symbol: str
    shares: Decimal
    price: Decimal
    gross_amount: Decimal
    fee: Decimal
    currency: str
    transaction_date: date
    sort_at: datetime


@dataclass
class TradeRepublicImportResult:
    trading_rows: int = 0
    inserted: int = 0
    sales_inserted: int = 0
    assets_created: int = 0
    skipped_duplicate: int = 0
    skipped_sell_without_asset: int = 0
    skipped_invalid: int = 0
    skipped_invalid_sell: int = 0
    liquid_adjusted: int = 0
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def parse_trade_republic_csv(csv_text: str) -> tuple[list[TradeRepublicTrade], TradeRepublicImportResult]:
    """Devuelve las operaciones TRADING BUY/SELL válidas y el recuento de lo descartado."""
    result = TradeRepublicImportResult()
    text = (csv_text or "").lstrip("\ufeff").strip()
    if not text:
        result.success = False
        result.error = "El CSV está vacío."
        return [], result

    header_line = text.splitlines()[0]
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","
    reader = csv.DictReader(StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None or "category" not in reader.fieldnames or "type" not in reader.fieldnames:
        result.success = False
        result.error = "El CSV no tiene las columnas de Trade Republic (category, type, name, symbol...)."
        return [], result

    trades: list[TradeRepublicTrade] = []
    for raw in reader:
        category = _cell(raw, "category").upper()
        side = _cell(raw, "type").upper()
        if category != "TRADING" or side not in {"BUY", "SELL"}:
            continue

        result.trading_rows += 1
        trade = _parse_trading_row(raw, side)
        if trade is None:
            result.skipped_invalid += 1
            result.messages.append(
                f"Fila TRADING {side} no válida ({_cell(raw, 'name') or _cell(raw, 'transaction_id') or 'sin id'})."
            )
            continue
        trades.append(trade)

    trades.sort(key=lambda item: (item.sort_at, item.transaction_id))
    return trades, result


def import_trade_republic_csv(db: Session, csv_text: str) -> TradeRepublicImportResult:
    trades, result = parse_trade_republic_csv(csv_text)
    if not result.success:
        return result
    if not trades:
        result.messages.append("No hay compras ni ventas TRADING en el CSV.")
        return result

    entity_id = get_settings().trade_republic_entity_id
    entity = db.get(Entity, entity_id)
    if entity is None or entity.entity_type != EntityType.HYBRID:
        result.success = False
        result.error = f"La entidad {entity_id!r} no existe o no es HYBRID."
        return result

    existing_ids = load_exchange_trade_ids_with_prefix(db, TRADE_ID_PREFIX)
    asset_ids = [str(asset.id) for asset in _known_trade_republic_assets(db, trades, entity_id)]
    position_totals = sum_position_by_asset_type_ids(db, asset_ids) if asset_ids else {}
    fills = _plan_fills(db, trades, result, entity_id, existing_ids, position_totals)

    if not fills:
        result.messages.append("No hay operaciones nuevas para insertar.")
        db.rollback()
        return result

    inserted, skipped_insert, inserted_fills = insert_transactions_batch(db, fills)
    result.inserted = inserted
    result.skipped_duplicate += skipped_insert

    sale_ids = _upsert_sales(db, inserted_fills)
    result.sales_inserted = len(sale_ids)

    snapshot_fills = [
        fill
        for fill in inserted_fills
        if Decimal(str(fill["asset_amount"])) > 0 or fill.get("exchange_trade_id") in sale_ids
    ]

    if snapshot_fills:
        apply_transactions_to_monthly_snapshot(db, snapshot_fills)
        hybrid = apply_auto_trades_to_hybrid_entities(db, snapshot_fills, source="trade_republic")
        result.liquid_adjusted = hybrid.fills_liquid_adjusted

    if result.inserted == 0 and result.assets_created == 0:
        result.messages.append("No hay operaciones nuevas para insertar.")
    return result


def _known_trade_republic_assets(
    db: Session, trades: list[TradeRepublicTrade], entity_id: str
) -> list[AssetType]:
    found: list[AssetType] = []
    seen: set[str] = set()
    for trade in trades:
        key = trade.name.upper()
        if key in seen:
            continue
        seen.add(key)
        asset = find_asset_by_name_and_entity(db, trade.name, entity_id)
        if asset is not None:
            found.append(asset)
    return found


def _plan_fills(
    db: Session,
    trades: list[TradeRepublicTrade],
    result: TradeRepublicImportResult,
    entity_id: str,
    existing_ids: set[str],
    position_totals: dict[str, tuple[Decimal, Decimal]],
) -> list[dict]:
    seen_ids: set[str] = set()
    resolved: list[tuple[TradeRepublicTrade, AssetType]] = []
    seen_names: dict[str, AssetType] = {}
    same_day = _load_same_day_operations(db, entity_id)

    for trade in trades:
        exchange_trade_id = f"{TRADE_ID_PREFIX}{trade.transaction_id}"
        if exchange_trade_id in existing_ids or exchange_trade_id in seen_ids:
            result.skipped_duplicate += 1
            continue
        seen_ids.add(exchange_trade_id)

        asset, created = _asset_for_trade(db, trade, entity_id, seen_names)
        if asset is None:
            if trade.side == "BUY":
                result.skipped_invalid += 1
                result.messages.append(f"No se pudo crear el activo {trade.name}.")
                logger.error(
                    "No se ha podido procesar la BUY %s (%s, %s, ref %s): no se crea el asset type",
                    trade.name,
                    trade.symbol,
                    trade.transaction_date,
                    trade.transaction_id,
                )
            else:
                result.skipped_sell_without_asset += 1
                logger.warning(
                    "No se ha podido procesar la SELL %s (%s, %s, ref %s): no hay asset type de Trade Republic",
                    trade.name,
                    trade.symbol,
                    trade.transaction_date,
                    trade.transaction_id,
                )
            continue
        if created:
            result.assets_created += 1
            logger.info(
                "Compra Trade Republic %s (%s, %s): se crea el asset type",
                trade.name,
                trade.symbol,
                trade.currency,
            )
        day_key = (str(asset.id), trade.transaction_date, trade.side)
        if day_key in same_day:
            result.skipped_duplicate += 1
            kind = "compra" if trade.side == "BUY" else "venta"
            logger.info(
                "Trade Republic %s %s (%s) %s: se omite, ya hay una %s ese día",
                trade.side,
                trade.name,
                trade.symbol,
                trade.transaction_date.isoformat(),
                kind,
            )
            continue
        same_day.add(day_key)
        resolved.append((trade, asset))

    fills, skipped_invalid_sell = _build_fills(resolved, position_totals)
    result.skipped_invalid_sell += skipped_invalid_sell
    return fills


def _load_same_day_operations(db: Session, entity_id: str) -> set[tuple[str, date, str]]:
    """(activo, día, BUY|SELL) ya registrados en esa entidad."""
    rows = db.execute(
        select(
            AssetTransaction.asset_type_id,
            AssetTransaction.transaction_date,
            AssetTransaction.asset_amount,
        )
        .join(AssetType, AssetTransaction.asset_type_id == AssetType.id)
        .where(AssetType.entity_id == entity_id)
    ).all()
    found: set[tuple[str, date, str]] = set()
    for asset_type_id, tx_date, amount in rows:
        if tx_date is None:
            continue
        side = "SELL" if Decimal(str(amount)) < 0 else "BUY"
        found.add((str(asset_type_id), tx_date, side))
    return found


def _asset_for_trade(
    db: Session,
    trade: TradeRepublicTrade,
    entity_id: str,
    seen_names: dict[str, AssetType],
) -> tuple[AssetType | None, bool]:
    key = trade.name.upper()
    cached = seen_names.get(key)
    if cached is not None:
        return cached, False

    existing = find_asset_by_name_and_entity(db, trade.name, entity_id)
    if existing is not None:
        seen_names[key] = existing
        return existing, False

    if trade.side != "BUY":
        return None, False

    created = create_trade_republic_asset(
        db,
        name=trade.name,
        ticker=trade.symbol,
        currency=trade.currency,
    )
    if created is None:
        return None, False
    seen_names[key] = created
    return created, True


def _build_fills(
    resolved: list[tuple[TradeRepublicTrade, AssetType]],
    position_totals: dict[str, tuple[Decimal, Decimal]],
) -> tuple[list[dict], int]:
    running: dict[str, tuple[Decimal, Decimal]] = {
        asset_id: (Decimal(str(units)), Decimal(str(invested)))
        for asset_id, (units, invested) in position_totals.items()
    }
    fills: list[dict] = []
    skipped_invalid_sell = 0

    for trade, asset in resolved:
        asset_type_id = str(asset.id)
        exchange_trade_id = f"{TRADE_ID_PREFIX}{trade.transaction_id}"
        units_before, invested_before = running.get(asset_type_id, (Decimal("0"), Decimal("0")))

        if trade.side == "BUY":
            invested = _q(trade.gross_amount + trade.fee)
            fills.append(
                {
                    "exchange_trade_id": exchange_trade_id,
                    "asset_type_id": asset_type_id,
                    "transaction_date": trade.transaction_date,
                    "invested_amount": invested,
                    "asset_amount": trade.shares,
                    "execution_price": trade.price,
                    "fee_amount": trade.fee,
                }
            )
            running[asset_type_id] = (units_before + trade.shares, invested_before + invested)
            _log_processed_trade(trade)
            continue

        if units_before <= 0:
            logger.warning(
                "No se ha podido procesar la SELL %s (%s, %s, ref %s): sin posición previa",
                trade.name,
                trade.symbol,
                trade.transaction_date,
                trade.transaction_id,
            )
            skipped_invalid_sell += 1
            continue

        sold_units = trade.shares
        avg_buy_price, invested_out = negative_invested_for_sell(
            units_before=units_before,
            invested_before=invested_before,
            sold_units=sold_units,
        )
        cost_removed = -invested_out
        net_liquidity = _q(trade.gross_amount - trade.fee)
        position_sold_pct = float(
            min(Decimal("100"), (sold_units / units_before * Decimal("100"))).quantize(Decimal("0.0001"))
        )
        fills.append(
            {
                "exchange_trade_id": exchange_trade_id,
                "asset_type_id": asset_type_id,
                "transaction_date": trade.transaction_date,
                "invested_amount": invested_out,
                "asset_amount": -sold_units,
                "execution_price": trade.price,
                "fee_amount": trade.fee,
                "net_liquidity": net_liquidity,
                "sale_payload": {
                    "units": float(sold_units),
                    "avg_buy_price": float(avg_buy_price),
                    "sale_price": float(trade.price.quantize(Decimal("0.0001"))),
                    "fee": float(trade.fee.quantize(Decimal("0.0001"))),
                    "net_liquidity": float(net_liquidity.quantize(Decimal("0.0001"))),
                    "position_sold_pct": position_sold_pct,
                    "sale_date": trade.transaction_date,
                },
            }
        )
        running[asset_type_id] = (units_before - sold_units, invested_before - cost_removed)
        _log_processed_trade(trade)

    return fills, skipped_invalid_sell


def _log_processed_trade(trade: TradeRepublicTrade) -> None:
    logger.info(
        "Trade Republic %s %s (%s) %s: %s títulos a %s %s",
        trade.side,
        trade.name,
        trade.symbol,
        trade.transaction_date.isoformat(),
        trade.shares,
        trade.price,
        trade.currency,
    )


def _upsert_sales(db: Session, inserted_fills: list[dict]) -> set[str]:
    inserted_ids: set[str] = set()
    for fill in inserted_fills:
        if Decimal(str(fill["asset_amount"])) >= 0:
            continue
        payload = fill.get("sale_payload")
        executed_at = fill.get("executed_at")
        if not payload or executed_at is None:
            continue
        upsert_kucoin_daily_asset_sale(
            db,
            {
                **payload,
                "asset_type_id": fill["asset_type_id"],
                "sale_year": executed_at.year,
                "sale_month": executed_at.month,
                "exchange_trade_id": fill["exchange_trade_id"],
            },
        )
        inserted_ids.add(str(fill["exchange_trade_id"]))
    if inserted_ids:
        db.commit()
    return inserted_ids


def _parse_trading_row(raw: dict[str, str | None], side: str) -> TradeRepublicTrade | None:
    transaction_id = _cell(raw, "transaction_id")
    name = " ".join(_cell(raw, "name").split())
    symbol = _cell(raw, "symbol").upper()
    currency = _CURRENCY.get(_cell(raw, "currency").upper().replace("Ó", "O"))
    shares = _abs_decimal(_cell(raw, "shares"))
    price = _abs_decimal(_cell(raw, "price"))
    gross = _abs_decimal(_cell(raw, "amount"))
    fee = _abs_decimal(_cell(raw, "fee")) or Decimal("0")
    transaction_date, sort_at = _parse_when(raw)

    if not transaction_id or not name or not symbol or currency is None:
        return None
    if shares is None or shares <= 0 or price is None or price <= 0 or gross is None:
        return None
    if transaction_date is None or sort_at is None:
        return None

    return TradeRepublicTrade(
        transaction_id=transaction_id[:80],
        side=side,
        name=name[:50],
        symbol=symbol[:20],
        shares=_q(shares),
        price=_q(price),
        gross_amount=_q(gross),
        fee=_q(fee),
        currency=currency,
        transaction_date=transaction_date,
        sort_at=sort_at,
    )


def _parse_when(raw: dict[str, str | None]) -> tuple[date | None, datetime | None]:
    raw_date = _cell(raw, "date")
    raw_dt = _cell(raw, "datetime")
    parsed_date: date | None = None
    parsed_dt: datetime | None = None
    if raw_date:
        try:
            parsed_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            parsed_date = None
    if raw_dt:
        try:
            parsed_dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        except ValueError:
            parsed_dt = None
    if parsed_date is None and parsed_dt is not None:
        parsed_date = parsed_dt.date()
    if parsed_dt is None and parsed_date is not None:
        parsed_dt = datetime(parsed_date.year, parsed_date.month, parsed_date.day)
    return parsed_date, parsed_dt


def _cell(raw: dict[str, str | None], key: str) -> str:
    return str(raw.get(key) or "").strip()


def _abs_decimal(raw: str) -> Decimal | None:
    if not raw:
        return None
    try:
        text = raw.replace(" ", "")
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        return abs(Decimal(text))
    except InvalidOperation:
        return None


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MONEY)
