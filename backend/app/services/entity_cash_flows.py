from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entity_cash_flow import EntityCashFlow


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def cash_flow_totals_by_entity(db: Session) -> dict[str, float]:
    """Suma de amount en entity_cash_flows agrupada por entity_id."""
    stmt = (
        select(EntityCashFlow.entity_id, func.coalesce(func.sum(EntityCashFlow.amount), 0))
        .where(EntityCashFlow.entity_id.is_not(None))
        .group_by(EntityCashFlow.entity_id)
    )
    return {entity_id: _round2(Decimal(str(total))) for entity_id, total in db.execute(stmt).all()}


def cash_flow_total_for_entity(db: Session, entity_id: str) -> float | None:
    """Suma de movimientos de caja de una entidad, o None si no tiene filas."""
    count = db.scalar(
        select(func.count()).select_from(EntityCashFlow).where(EntityCashFlow.entity_id == entity_id)
    )
    if not count:
        return None

    total = db.scalar(
        select(func.coalesce(func.sum(EntityCashFlow.amount), 0)).where(EntityCashFlow.entity_id == entity_id)
    )
    return _round2(Decimal(str(total or 0)))
