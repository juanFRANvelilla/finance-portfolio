"""Cálculo del invertido estático de cuentas híbridas vía libro de aportaciones."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entity import Entity, EntityType
from app.models.entity_contribution import EntityContribution
from app.models.monthly_hybrid_account import MonthlyHybridAccount
from app.models.monthly_record import MonthlyRecord


def _round2(value: Decimal | float | int) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _month_date_range(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def uses_ledger(entity: Entity) -> bool:
    """True si la híbrida gestiona el preview de invertido vía aportaciones."""
    return entity.entity_type == EntityType.HYBRID and bool(entity.uses_contribution_ledger)


def get_previous_static_total(db: Session, entity_id: str, year: int, month: int) -> float:
    """Total estático del mes anterior: liquid + cumulative_invested de la híbrida."""
    prev_year, prev_month = _previous_year_month(year, month)
    stmt = (
        select(MonthlyHybridAccount)
        .join(MonthlyRecord, MonthlyHybridAccount.record_id == MonthlyRecord.id)
        .where(
            MonthlyRecord.year == prev_year,
            MonthlyRecord.month == prev_month,
            MonthlyHybridAccount.entity_id == entity_id,
        )
    )
    hybrid = db.scalars(stmt).first()
    if hybrid is None:
        return 0.0
    total = Decimal(str(hybrid.liquid_amount)) + Decimal(str(hybrid.cumulative_invested))
    return _round2(total)


def sum_contributions_for_month(db: Session, entity_id: str, year: int, month: int) -> float:
    start, end = _month_date_range(year, month)
    stmt = select(EntityContribution).where(
        EntityContribution.entity_id == entity_id,
        EntityContribution.contribution_date >= start,
        EntityContribution.contribution_date <= end,
    )
    rows = list(db.scalars(stmt).all())
    total = sum((Decimal(str(row.amount)) for row in rows), Decimal("0"))
    return _round2(total)


def compute_cumulative_invested(
    db: Session, entity_id: str, year: int, month: int, liquid_amount: float
) -> float:
    """Invertido = (total estático anterior + aportaciones del mes) − líquido actual."""
    previous_total = Decimal(str(get_previous_static_total(db, entity_id, year, month)))
    contributions = Decimal(str(sum_contributions_for_month(db, entity_id, year, month)))
    liquid = Decimal(str(liquid_amount))
    invested = previous_total + contributions - liquid
    return _round2(invested)


def build_ledger_summary(
    db: Session, entity_id: str, year: int, month: int, liquid_amount: float = 0.0
) -> dict[str, float]:
    previous_total = get_previous_static_total(db, entity_id, year, month)
    contributions_total = sum_contributions_for_month(db, entity_id, year, month)
    projected_total = _round2(Decimal(str(previous_total)) + Decimal(str(contributions_total)))
    cumulative_invested = _round2(Decimal(str(projected_total)) - Decimal(str(liquid_amount)))
    return {
        "previous_static_total": previous_total,
        "contributions_total": contributions_total,
        "projected_total": projected_total,
        "cumulative_invested": cumulative_invested,
    }
