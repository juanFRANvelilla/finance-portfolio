"""Apertura del mes natural en monthly_entity_positions (copia del cierre anterior)."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entity import Entity, EntityType
from app.models.monthly_entity_position import MonthlyEntityPosition
from app.services.monthly_asset_snapshot import _next_year_month

logger = logging.getLogger(__name__)


def _load_position(db: Session, *, entity_id: str, year: int, month: int) -> MonthlyEntityPosition | None:
    return db.scalars(
        select(MonthlyEntityPosition).where(
            MonthlyEntityPosition.entity_id == entity_id,
            MonthlyEntityPosition.year == year,
            MonthlyEntityPosition.month == month,
        )
    ).first()


def _default_invested_for_entity(entity_type: EntityType) -> Decimal | None:
    if entity_type == EntityType.LIQUID:
        return None
    return Decimal("0")


def ensure_current_month_entity_positions(db: Session, *, today: date | None = None) -> int:
    """Crea filas del mes actual para cada entidad activa que aún no las tenga.

    Copia ``liquid_amount`` e ``invested_amount`` de la última fila anterior,
    rellenando meses intermedios si hace falta. Sin histórico: líquido 0 e
    invertido NULL (LIQUID) o 0 (HYBRID). Idempotente por (entity, year, month).
    """
    current = today or date.today()
    target = (current.year, current.month)

    entities = list(db.scalars(select(Entity).where(Entity.is_active.is_(True)).order_by(Entity.id)).all())
    created = 0

    for entity in entities:
        latest = db.scalars(
            select(MonthlyEntityPosition)
            .where(MonthlyEntityPosition.entity_id == entity.id)
            .order_by(MonthlyEntityPosition.year.desc(), MonthlyEntityPosition.month.desc())
        ).first()

        if latest is None:
            if _load_position(db, entity_id=entity.id, year=target[0], month=target[1]) is not None:
                continue
            db.add(
                MonthlyEntityPosition(
                    year=target[0],
                    month=target[1],
                    entity_id=entity.id,
                    liquid_amount=Decimal("0"),
                    invested_amount=_default_invested_for_entity(entity.entity_type),
                )
            )
            created += 1
            logger.info(
                "monthly_entity_positions abierto para entity_id=%s %s-%02d (sin histórico, valores iniciales)",
                entity.id,
                target[0],
                target[1],
            )
            continue

        year, month = latest.year, latest.month
        liquid = Decimal(str(latest.liquid_amount))
        invested = (
            None
            if latest.invested_amount is None
            else Decimal(str(latest.invested_amount))
        )

        while (year, month) < target:
            year, month = _next_year_month(year, month)
            existing = _load_position(db, entity_id=entity.id, year=year, month=month)
            if existing is not None:
                liquid = Decimal(str(existing.liquid_amount))
                invested = (
                    None
                    if existing.invested_amount is None
                    else Decimal(str(existing.invested_amount))
                )
                continue

            row_invested = (
                None if entity.entity_type == EntityType.LIQUID else invested
            )
            db.add(
                MonthlyEntityPosition(
                    year=year,
                    month=month,
                    entity_id=entity.id,
                    liquid_amount=liquid,
                    invested_amount=row_invested,
                )
            )
            created += 1
            logger.info(
                "monthly_entity_positions abierto para entity_id=%s %s-%02d (copiado del cierre anterior)",
                entity.id,
                year,
                month,
            )

    if created:
        db.commit()
    return created


def run_ensure_current_month_entity_positions() -> int:
    with SessionLocal() as db:
        return ensure_current_month_entity_positions(db)
