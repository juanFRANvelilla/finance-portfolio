from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset_type import AssetType
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.services.fx_converter import amount_to_eur


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def sum_linked_asset_investments_eur(db: Session, entity_id: str, year: int, month: int) -> dict[str, float | int]:
    """Suma en EUR los monthly_asset_investments de activos vinculados a la entidad."""
    stmt = (
        select(AssetType.currency, MonthlyAssetInvestment.amount)
        .join(MonthlyAssetInvestment, MonthlyAssetInvestment.asset_type_id == AssetType.id)
        .where(
            AssetType.entity_id == entity_id,
            AssetType.is_active.is_(True),
            MonthlyAssetInvestment.year == year,
            MonthlyAssetInvestment.month == month,
        )
    )

    total = Decimal("0")
    asset_count = 0
    for currency, amount in db.execute(stmt).all():
        asset_count += 1
        total += Decimal(str(amount_to_eur(float(amount), currency, year, month)))

    return {"total_eur": _round2(total), "asset_count": asset_count}
