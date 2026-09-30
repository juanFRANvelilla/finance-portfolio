"""Inserciones idempotentes en entity_cash_flows."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session


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
