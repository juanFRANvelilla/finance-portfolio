from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset_transaction import AssetTransaction


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _round8(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.00000001")))


def transaction_totals_by_asset_type(db: Session, asset_type_ids: list[UUID]) -> dict[UUID, dict[str, float]]:
    """Suma invested_amount (EUR) y asset_amount por activo."""
    if not asset_type_ids:
        return {}

    stmt = (
        select(
            AssetTransaction.asset_type_id,
            func.coalesce(func.sum(AssetTransaction.invested_amount), 0),
            func.coalesce(func.sum(AssetTransaction.asset_amount), 0),
        )
        .where(AssetTransaction.asset_type_id.in_(asset_type_ids))
        .group_by(AssetTransaction.asset_type_id)
    )
    return {
        asset_type_id: {
            "invested_amount_eur": _round2(Decimal(str(invested))),
            "asset_amount": _round8(Decimal(str(units))),
        }
        for asset_type_id, invested, units in db.execute(stmt).all()
    }
