"""Sincronización de confirmaciones MyInvestor (IMAP) hacia asset_transactions y asset_sales.

Flujo paralelo al de KuCoin: no comparte extracción ni transformación.
Compras: `invested_amount`, precio neto/unidad y comisión en divisa de `asset_types`.
Ventas: unidades negativas, `invested_amount` negativo (coste PMP), precio bruto; fila en `asset_sales`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.myinvestor.mail import fetch_mailbox_messages
from app.myinvestor.trades.parse_trade import (
    ParsedMyInvestorTrade,
    amounts_for_asset_currency,
    diagnose_myinvestor_parse,
    is_purchase_side,
    is_sale_side,
    looks_like_trade_confirmation,
    parse_myinvestor_trade,
    sell_amounts_for_asset_currency,
)
from app.repositories.asset_sales import upsert_kucoin_daily_asset_sale
from app.repositories.asset_transactions import (
    insert_transactions_batch,
    load_asset_match_index,
    load_exchange_trade_ids_with_prefix,
    sum_position_by_asset_type_ids,
)
from app.services.hybrid_entity_auto_adjust import apply_auto_trades_to_hybrid_entities
from app.services.monthly_asset_snapshot import apply_transactions_to_monthly_snapshot
from app.services.transaction_pmp import negative_invested_for_sell

logger = logging.getLogger(__name__)

TRADE_ID_PREFIX = "myinvestor:"

MYINVESTOR_ID_ALIASES = {
    "FR0013416716": "FR0013416716.SG",
    "US5949181045": "MSF.DE",
}


def myinvestor_asset_lookup_keys(ticker: str, isin: str) -> list[str]:
    keys: list[str] = []
    for raw in (ticker, isin):
        normalized = (raw or "").upper()
        if not normalized:
            continue
        if normalized not in keys:
            keys.append(normalized)
        alias = MYINVESTOR_ID_ALIASES.get(normalized)
        if alias and alias not in keys:
            keys.append(alias)
    return keys


@dataclass
class _ResolvedTrade:
    trade: ParsedMyInvestorTrade
    asset_type_id: str
    asset_currency: str


@dataclass
class MyInvestorSyncResult:
    raw_emails_count: int = 0
    candidates: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_not_trade: int = 0
    skipped_unparsed: int = 0
    skipped_unknown_asset: int = 0
    skipped_currency: int = 0
    skipped_invalid_sell: int = 0
    sales_inserted: int = 0
    snapshot_fills_skipped_not_current_month: int = 0
    snapshot_groups_processed: int = 0
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def _build_fills_from_trades(
    trades: list[_ResolvedTrade],
    *,
    existing_trade_ids: set[str],
    position_totals: dict[str, tuple[Decimal, Decimal]],
) -> tuple[list[dict], int, int]:
    """Orden cronológico; PMP con posición en BD; omite refs ya importadas."""
    skipped_duplicate = 0
    skipped_invalid_sell = 0
    sorted_trades = sorted(
        trades,
        key=lambda item: (item.trade.transaction_date, item.trade.reference),
    )

    running: dict[str, tuple[Decimal, Decimal]] = {
        asset_id: (Decimal(str(units)), Decimal(str(invested)))
        for asset_id, (units, invested) in position_totals.items()
    }
    fills: list[dict] = []

    for item in sorted_trades:
        trade = item.trade
        asset_type_id = item.asset_type_id
        exchange_trade_id = f"{TRADE_ID_PREFIX}{trade.reference}"

        if exchange_trade_id in existing_trade_ids:
            skipped_duplicate += 1
            continue

        if is_purchase_side(trade.side):
            amounts = amounts_for_asset_currency(trade, item.asset_currency)
            if amounts is None:
                continue
            fills.append(
                {
                    "exchange_trade_id": exchange_trade_id,
                    "asset_type_id": asset_type_id,
                    "transaction_date": trade.transaction_date,
                    "invested_amount": amounts.invested_amount,
                    "asset_amount": amounts.asset_amount,
                    "execution_price": amounts.execution_price,
                    "fee_amount": amounts.fee_amount,
                }
            )
            units_before, invested_before = running.get(
                asset_type_id, (Decimal("0"), Decimal("0"))
            )
            running[asset_type_id] = (
                units_before + amounts.asset_amount,
                invested_before + amounts.invested_amount,
            )
            continue

        if not is_sale_side(trade.side):
            continue

        amounts = sell_amounts_for_asset_currency(trade, item.asset_currency)
        if amounts is None:
            continue

        units_before, invested_before = running.get(
            asset_type_id, (Decimal("0"), Decimal("0"))
        )
        if units_before <= 0:
            logger.warning(
                "Venta MyInvestor omitida (sin posición previa): ref=%s asset=%s",
                trade.reference,
                trade.ticker,
            )
            skipped_invalid_sell += 1
            continue

        sold_units = trade.asset_amount
        avg_buy_price, invested_out = negative_invested_for_sell(
            units_before=units_before,
            invested_before=invested_before,
            sold_units=sold_units,
        )
        cost_removed = -invested_out
        if units_before > 0:
            position_sold_pct = float(
                min(
                    Decimal("100"),
                    (sold_units / units_before * Decimal("100")),
                ).quantize(Decimal("0.0001"))
            )
        else:
            position_sold_pct = 100.0

        fills.append(
            {
                "exchange_trade_id": exchange_trade_id,
                "asset_type_id": asset_type_id,
                "transaction_date": trade.transaction_date,
                "invested_amount": invested_out,
                "asset_amount": amounts.asset_amount,
                "execution_price": amounts.execution_price,
                "fee_amount": amounts.fee_amount,
                "net_liquidity": amounts.net_liquidity,
                "sale_payload": {
                    "units": float(sold_units.quantize(Decimal("0.00000001"))),
                    "avg_buy_price": float(avg_buy_price),
                    "sale_price": float(amounts.execution_price.quantize(Decimal("0.0001"))),
                    "fee": float(amounts.fee_amount.quantize(Decimal("0.0001"))),
                    "net_liquidity": float(amounts.net_liquidity.quantize(Decimal("0.0001"))),
                    "position_sold_pct": position_sold_pct,
                    "sale_date": trade.transaction_date,
                },
            }
        )
        running[asset_type_id] = (
            units_before - sold_units,
            invested_before - cost_removed,
        )

    return fills, skipped_duplicate, skipped_invalid_sell


def _upsert_sales_for_inserted_sells(db, inserted_fills: list[dict]) -> set[str]:
    """Crea/actualiza asset_sales por venta insertada; sale_year/month = executed_at."""
    upserted_ids: set[str] = set()
    for fill in inserted_fills:
        if Decimal(str(fill["asset_amount"])) >= 0:
            continue
        payload = fill.get("sale_payload")
        executed_at = fill.get("executed_at")
        if not payload or executed_at is None:
            logger.warning(
                "Venta MyInvestor sin sale_payload/executed_at: %s",
                fill.get("exchange_trade_id"),
            )
            continue

        row = {
            **payload,
            "asset_type_id": fill["asset_type_id"],
            "sale_year": executed_at.year,
            "sale_month": executed_at.month,
            "exchange_trade_id": fill["exchange_trade_id"],
        }
        upsert_kucoin_daily_asset_sale(db, row)
        upserted_ids.add(fill["exchange_trade_id"])
    if upserted_ids:
        db.commit()
    return upserted_ids


def sync_myinvestor_transactions(
    *,
    dump_unparsed_bodies: bool = False,
) -> MyInvestorSyncResult:
    """Lee la etiqueta IMAP e inserta compras y ventas (idempotente por referencia)."""
    result = MyInvestorSyncResult()
    settings = get_settings()

    if not settings.imap_user or not settings.imap_password:
        result.success = False
        result.error = "Faltan credenciales IMAP. Define IMAP_USER e IMAP_PASSWORD."
        logger.warning(result.error)
        return result

    try:
        messages = fetch_mailbox_messages(
            host=settings.imap_host,
            port=settings.imap_port,
            user=settings.imap_user,
            password=settings.imap_password,
            mailbox=settings.myinvestor_imap_mailbox_movements,
        )
        result.raw_emails_count = len(messages)
        if not messages:
            result.messages.append(
                f"No hay correos en {settings.myinvestor_imap_mailbox_movements!r}."
            )
            logger.info(
                "MyInvestor sync: 0 correos en %s", settings.myinvestor_imap_mailbox_movements
            )
            return result

        with SessionLocal() as db:
            asset_index = load_asset_match_index(db)
            if not asset_index:
                result.success = False
                result.error = "No hay activos con ticker o name en asset_types."
                logger.error(result.error)
                return result

            resolved: list[_ResolvedTrade] = []
            for message in messages:
                if not looks_like_trade_confirmation(message.body):
                    continue

                trade = parse_myinvestor_trade(message.body)
                if trade is None:
                    result.skipped_unparsed += 1
                    reasons = diagnose_myinvestor_parse(message.body)
                    logger.warning(
                        "Correo MyInvestor no interpretable (UID=%s, asunto=%r): %s",
                        message.uid,
                        message.subject,
                        "; ".join(reasons) if reasons else "motivo desconocido",
                    )
                    if dump_unparsed_bodies:
                        print(f"\n{'=' * 60}")
                        print(f"CORREO NO INTERPRETABLE  UID={message.uid}")
                        print(f"Asunto: {message.subject}")
                        if reasons:
                            print("Diagnóstico:")
                            for reason in reasons:
                                print(f"  - {reason}")
                        print(f"{'-' * 60}")
                        print("Cuerpo exacto:")
                        print(message.body)
                        print(f"{'=' * 60}\n")
                    continue

                if not is_purchase_side(trade.side) and not is_sale_side(trade.side):
                    result.skipped_not_trade += 1
                    logger.info(
                        "Operación %s %s omitida (lado no soportado)",
                        trade.side,
                        trade.reference,
                    )
                    continue

                asset = next(
                    (
                        asset_index[key]
                        for key in myinvestor_asset_lookup_keys(trade.ticker, trade.isin)
                        if key in asset_index
                    ),
                    None,
                )
                if asset is None:
                    result.skipped_unknown_asset += 1
                    logger.warning(
                        "Activo '%s' (ISIN %s, ref %s) no encontrado en asset_types",
                        trade.ticker,
                        trade.isin,
                        trade.reference,
                    )
                    continue

                if is_purchase_side(trade.side):
                    if amounts_for_asset_currency(trade, asset.currency) is None:
                        result.skipped_currency += 1
                        logger.warning(
                            "No se puede expresar compra %s en divisa %s del activo",
                            trade.reference,
                            asset.currency,
                        )
                        continue
                elif sell_amounts_for_asset_currency(trade, asset.currency) is None:
                    result.skipped_currency += 1
                    logger.warning(
                        "No se puede expresar venta %s en divisa %s del activo",
                        trade.reference,
                        asset.currency,
                    )
                    continue

                resolved.append(
                    _ResolvedTrade(
                        trade=trade,
                        asset_type_id=asset.asset_type_id,
                        asset_currency=asset.currency,
                    )
                )

            existing_ids = load_exchange_trade_ids_with_prefix(db, TRADE_ID_PREFIX)
            asset_ids = list({item.asset_type_id for item in resolved})
            position_totals = sum_position_by_asset_type_ids(db, asset_ids)

            fills, skipped_dup, skipped_invalid_sell = _build_fills_from_trades(
                resolved,
                existing_trade_ids=existing_ids,
                position_totals=position_totals,
            )
            result.skipped_duplicate = skipped_dup
            result.skipped_invalid_sell = skipped_invalid_sell
            result.candidates = len(fills)

            if not fills:
                result.messages.append("No hay operaciones nuevas para insertar.")
                return result

            inserted, skipped_insert, inserted_fills = insert_transactions_batch(db, fills)
            result.inserted = inserted
            result.skipped_duplicate += skipped_insert

            upserted_sale_ids = _upsert_sales_for_inserted_sells(db, inserted_fills)
            result.sales_inserted = len(upserted_sale_ids)

            snapshot_fills: list[dict] = []
            for fill in inserted_fills:
                if Decimal(str(fill["asset_amount"])) < 0:
                    if fill.get("exchange_trade_id") not in upserted_sale_ids:
                        continue
                snapshot_fills.append(fill)

            if snapshot_fills:
                snapshot_result = apply_transactions_to_monthly_snapshot(db, snapshot_fills)
                result.snapshot_fills_skipped_not_current_month = (
                    snapshot_result.fills_skipped_not_current_month
                )
                result.snapshot_groups_processed = snapshot_result.groups_processed

            if inserted_fills:
                hybrid_fills = snapshot_fills if snapshot_fills else [
                    f for f in inserted_fills if Decimal(str(f.get("asset_amount", 0))) > 0
                ]
                if hybrid_fills:
                    apply_auto_trades_to_hybrid_entities(db, hybrid_fills, source="myinvestor")

        logger.info(
            "MyInvestor sync OK: %s tx insertadas, %s ventas asset_sales, "
            "%s duplicados omitidos (%s correos)",
            result.inserted,
            result.sales_inserted,
            result.skipped_duplicate,
            result.raw_emails_count,
        )
        return result

    except Exception as exc:
        result.success = False
        result.error = str(exc)
        logger.exception("MyInvestor sync falló: %s", exc)
        return result


def run_scheduled_myinvestor_sync() -> MyInvestorSyncResult:
    logger.info("Sync MyInvestor: leyendo confirmaciones de la etiqueta IMAP")
    return sync_myinvestor_transactions()
