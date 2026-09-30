"""Inserciones idempotentes en entity_cash_flows."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# Primer depósito fiat EUR que queremos sincronizar automáticamente desde API.
KUCOIN_FIAT_SYNC_FALLBACK_START = datetime(2025, 12, 25)
KUCOIN_FIAT_SOURCE_PREFIX = "kucoin:fiat-"


def resolve_kucoin_fiat_sync_start_datetime(db: Session, entity_id: str) -> datetime:
    """Desde la última flow_date API de KuCoin (con 1 día de solape) o fallback fijo."""
    max_flow_date = db.execute(
        text(
            """
            SELECT MAX(flow_date)
            FROM public.entity_cash_flows
            WHERE entity_id = :entity_id
              AND source_reference LIKE :prefix
            """
        ),
        {"entity_id": entity_id, "prefix": f"{KUCOIN_FIAT_SOURCE_PREFIX}%"},
    ).scalar()

    if max_flow_date is None:
        return KUCOIN_FIAT_SYNC_FALLBACK_START

    start = datetime.combine(max_flow_date, datetime.min.time()) - timedelta(days=1)
    if start < KUCOIN_FIAT_SYNC_FALLBACK_START:
        return KUCOIN_FIAT_SYNC_FALLBACK_START
    return start


def insert_cash_flows_batch(db: Session, rows: list[dict]) -> tuple[int, int]:
    """Inserta filas con ON CONFLICT (source_reference) DO NOTHING.

    Cada dict: entity_id, amount, flow_date, source_reference.
    Devuelve (insertados, omitidos_por_duplicado).
    """
    insertados = 0
    omitidos = 0

    for row in rows:
        result = db.execute(
            text(
                """
                INSERT INTO public.entity_cash_flows
                    (id, entity_id, amount, flow_date, source_reference, created_at)
                VALUES
                    (:id, :entity_id, :amount, :flow_date, :source_reference, NOW())
                ON CONFLICT (source_reference) DO NOTHING
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "entity_id": row["entity_id"],
                "amount": row["amount"],
                "flow_date": row["flow_date"],
                "source_reference": row["source_reference"],
            },
        )
        if result.rowcount == 0:
            omitidos += 1
        else:
            insertados += 1

    return insertados, omitidos
