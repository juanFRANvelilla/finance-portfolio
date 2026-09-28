"""Sincronización de confirmaciones MyInvestor (IMAP) hacia asset_transactions.

Flujo paralelo al de KuCoin: no comparte extracción ni transformación.
`invested_amount`, `execution_price` y `fee_amount` se guardan en la divisa de
`asset_types.currency`. La fila no lleva columna de divisa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.myinvestor.mail import fetch_mailbox_messages
from app.myinvestor.parse_trade import (
    amounts_for_asset_currency,
    looks_like_trade_confirmation,
    parse_myinvestor_trade,
)
from app.repositories.asset_transactions import insert_transactions_batch, load_asset_match_index

logger = logging.getLogger(__name__)

TRADE_ID_PREFIX = "myinvestor:"


@dataclass
class MyInvestorSyncResult:
    raw_emails_count: int = 0
    candidates: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_not_buy: int = 0
    skipped_unparsed: int = 0
    skipped_unknown_asset: int = 0
    skipped_currency: int = 0
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def sync_myinvestor_transactions() -> MyInvestorSyncResult:
    """Lee la etiqueta IMAP de MyInvestor e inserta compras en asset_transactions."""
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
            mailbox=settings.imap_mailbox,
        )
        result.raw_emails_count = len(messages)
        if not messages:
            result.messages.append(f"No hay correos en {settings.imap_mailbox!r}.")
            logger.info("MyInvestor sync: 0 correos en %s", settings.imap_mailbox)
            return result

        with SessionLocal() as db:
            asset_index = load_asset_match_index(db)
            if not asset_index:
                result.success = False
                result.error = "No hay activos con ticker o name en asset_types."
                logger.error(result.error)
                return result

            fills: list[dict] = []
            for message in messages:
                if not looks_like_trade_confirmation(message.body):
                    continue

                trade = parse_myinvestor_trade(message.body)
                if trade is None:
                    result.skipped_unparsed += 1
                    logger.warning(
                        "Correo MyInvestor no interpretable (UID=%s, asunto=%r)",
                        message.uid,
                        message.subject,
                    )
                    continue

                if trade.side != "COMPRA":
                    result.skipped_not_buy += 1
                    logger.info(
                        "Operación %s %s omitida (solo se importan compras)",
                        trade.side,
                        trade.reference,
                    )
                    continue

                asset = asset_index.get(trade.ticker)
                if asset is None:
                    result.skipped_unknown_asset += 1
                    logger.warning(
                        "Activo '%s' (ISIN %s, ref %s) no encontrado en asset_types",
                        trade.ticker,
                        trade.isin,
                        trade.reference,
                    )
                    continue

                amounts = amounts_for_asset_currency(trade, asset.currency)
                if amounts is None:
                    result.skipped_currency += 1
                    logger.warning(
                        "No se puede expresar %s %s en la divisa %s del activo %s",
                        trade.reference,
                        trade.trade_currency,
                        asset.currency,
                        trade.ticker,
                    )
                    continue

                exchange_trade_id = f"{TRADE_ID_PREFIX}{trade.reference}"
                fills.append(
                    {
                        "exchange_trade_id": exchange_trade_id,
                        "asset_type_id": asset.asset_type_id,
                        "transaction_date": trade.transaction_date,
                        "invested_amount": amounts.invested_amount,
                        "asset_amount": amounts.asset_amount,
                        "execution_price": amounts.execution_price,
                        "fee_amount": amounts.fee_amount,
                    }
                )

            result.candidates = len(fills)
            if not fills:
                result.messages.append("No hay operaciones válidas para insertar.")
                return result

            inserted, skipped = insert_transactions_batch(db, fills)
            result.inserted = inserted
            result.skipped_duplicate = skipped

        logger.info(
            "MyInvestor sync OK: %s insertados, %s duplicados omitidos (%s correos)",
            result.inserted,
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
    """Ejecuta la sincronización IMAP completa. Los duplicados los frena exchange_trade_id."""
    logger.info("Sync MyInvestor: leyendo confirmaciones de la etiqueta IMAP")
    return sync_myinvestor_transactions()
