"""Sync KuCoin fiat EUR (ledger) → entity_cash_flows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.repositories.entity_cash_flows import (
    insert_cash_flows_batch,
    resolve_kucoin_fiat_sync_start_datetime,
)
from app.services.kucoin_fiat_transfers_service import (
    KucoinFiatTransfer,
    ProgressCallback,
    fetch_kucoin_eur_fiat_transfers,
)

logger = logging.getLogger(__name__)

KUCOIN_FIAT_DEPOSIT_REF_PREFIX = "kucoin:fiat-deposit:"
KUCOIN_FIAT_WITHDRAW_REF_PREFIX = "kucoin:fiat-withdraw:"


@dataclass
class KucoinFiatCashFlowsSyncResult:
    start_date: datetime
    end_date: datetime
    candidates: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _source_reference(transfer: KucoinFiatTransfer) -> str:
    if transfer.direction == "deposit":
        return f"{KUCOIN_FIAT_DEPOSIT_REF_PREFIX}{transfer.transfer_id}"
    return f"{KUCOIN_FIAT_WITHDRAW_REF_PREFIX}{transfer.transfer_id}"


def _signed_amount(transfer: KucoinFiatTransfer) -> float:
    """Depósito +importe bruto; retiro −importe bruto (fee aparte en API)."""
    amount = Decimal(str(transfer.amount))
    signed = amount if transfer.direction == "deposit" else -amount
    return _round2(signed)


def sync_kucoin_fiat_cash_flows(
    start_date: datetime,
    end_date: datetime | None = None,
    *,
    on_progress: ProgressCallback | None = None,
) -> KucoinFiatCashFlowsSyncResult:
    settings = get_settings()
    entity_id = settings.kucoin_entity_id
    end = end_date or datetime.now()

    result = KucoinFiatCashFlowsSyncResult(start_date=start_date, end_date=end)

    if not settings.kucoin_api_key or not settings.kucoin_secret or not settings.kucoin_passphrase:
        result.success = False
        result.error = "Faltan credenciales KuCoin (KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE)."
        return result

    try:
        fetch_result = fetch_kucoin_eur_fiat_transfers(
            start_date,
            end_date=end,
            on_progress=on_progress,
        )
        if not fetch_result.success:
            result.success = False
            result.error = fetch_result.error or "Error al consultar KuCoin."
            return result

        rows_to_insert: list[dict] = []
        for transfer in fetch_result.transfers:
            if transfer.created_at < start_date:
                continue

            flow_date = transfer.created_at.date()
            amount = _signed_amount(transfer)
            source_reference = _source_reference(transfer)

            rows_to_insert.append(
                {
                    "entity_id": entity_id,
                    "amount": amount,
                    "flow_date": flow_date,
                    "source_reference": source_reference,
                }
            )
            result.messages.append(
                f"OK {transfer.direction} {flow_date} {amount:+.2f} EUR ref={source_reference}"
            )

        result.candidates = len(rows_to_insert)

        if rows_to_insert:
            with SessionLocal() as db:
                inserted, duplicates = insert_cash_flows_batch(db, rows_to_insert)
                db.commit()
                result.inserted = inserted
                result.skipped_duplicate = duplicates

        logger.info(
            "KuCoin fiat cash flows: %s insertados, %s duplicados (desde %s)",
            result.inserted,
            result.skipped_duplicate,
            start_date.date(),
        )
        return result

    except Exception as exc:
        result.success = False
        result.error = str(exc)
        logger.exception("KuCoin fiat cash flows sync falló: %s", exc)
        return result


def run_scheduled_kucoin_fiat_cash_flows_sync() -> KucoinFiatCashFlowsSyncResult:
    """Sync programada: rango dinámico desde MAX(flow_date) con ref KuCoin fiat."""
    settings = get_settings()
    with SessionLocal() as db:
        start_date = resolve_kucoin_fiat_sync_start_datetime(db, settings.kucoin_entity_id)

    logger.info("Sync KuCoin fiat EUR (entity_cash_flows) desde %s", start_date.date())
    return sync_kucoin_fiat_cash_flows(start_date, on_progress=None)
