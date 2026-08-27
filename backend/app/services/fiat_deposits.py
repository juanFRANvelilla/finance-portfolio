from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.fiat_deposit import FiatDeposit


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def fiat_deposit_totals_by_entity(db: Session) -> dict[str, float]:
    """Suma de amount en fiat_deposits agrupada por entity_id."""
    stmt = (
        select(FiatDeposit.entity_id, func.coalesce(func.sum(FiatDeposit.amount), 0))
        .where(FiatDeposit.entity_id.is_not(None))
        .group_by(FiatDeposit.entity_id)
    )
    return {entity_id: _round2(Decimal(str(total))) for entity_id, total in db.execute(stmt).all()}


def fiat_deposit_total_for_entity(db: Session, entity_id: str) -> float | None:
    """Suma de depósitos fiat de una entidad, o None si no tiene filas."""
    count = db.scalar(
        select(func.count()).select_from(FiatDeposit).where(FiatDeposit.entity_id == entity_id)
    )
    if not count:
        return None

    total = db.scalar(
        select(func.coalesce(func.sum(FiatDeposit.amount), 0)).where(FiatDeposit.entity_id == entity_id)
    )
    return _round2(Decimal(str(total or 0)))
