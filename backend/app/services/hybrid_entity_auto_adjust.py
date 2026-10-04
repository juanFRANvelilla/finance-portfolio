"""Actualiza monthly_entity_positions tras compras/ventas automáticas (KuCoin / MyInvestor)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.models.monthly_entity_position import MonthlyEntityPosition
from app.services.fx_converter import amount_to_eur
from app.services.linked_asset_investments import sum_linked_asset_investments_eur

logger = logging.getLogger(__name__)

AutoTradeSource = Literal["kucoin", "myinvestor"]
_MONEY = Decimal("0.01")


@dataclass
class HybridAutoAdjustResult:
    fills_liquid_adjusted: int = 0
    fills_skipped: int = 0
    entities_recalculated: int = 0
    skip_reasons: list[str] = field(default_factory=list)


def _executed_year_month(fill: dict) -> tuple[int, int] | None:
    executed_at = fill.get("executed_at")
    if executed_at is None:
        return None
    if isinstance(executed_at, datetime):
        return executed_at.year, executed_at.month
    return None


def _native_cash_delta_for_fill(
    fill: dict,
    *,
    source: AutoTradeSource,
) -> Decimal | None:
    """Importe en divisa del activo: compra negativo (sale cash), venta positivo (entra cash)."""
    asset_amount = Decimal(str(fill["asset_amount"]))
    fee = Decimal(str(fill.get("fee_amount") or 0))

    if asset_amount > 0:
        invested = Decimal(str(fill.get("invested_amount") or 0))
        if source == "myinvestor":
            cash_out = invested
        else:
            cash_out = invested + fee
        return -cash_out

    if asset_amount < 0:
        if source == "myinvestor":
            return None
        units = abs(asset_amount)
        price = Decimal(str(fill.get("execution_price") or 0))
        return units * price - fee

    return None


def _liquid_delta_eur(
    fill: dict,
    *,
    currency: str,
    year: int,
    month: int,
    source: AutoTradeSource,
) -> Decimal | None:
    native = _native_cash_delta_for_fill(fill, source=source)
    if native is None:
        return None
    eur = Decimal(str(amount_to_eur(float(native), currency, year, month)))
    return eur.quantize(_MONEY)


def _monthly_asset_row_exists(db: Session, *, asset_type_id: str, year: int, month: int) -> bool:
    row_id = db.scalar(
        select(MonthlyAssetInvestment.id).where(
            MonthlyAssetInvestment.asset_type_id == asset_type_id,
            MonthlyAssetInvestment.year == year,
            MonthlyAssetInvestment.month == month,
        )
    )
    return row_id is not None


def _load_entity_position(
    db: Session, *, entity_id: str, year: int, month: int
) -> MonthlyEntityPosition | None:
    return db.scalars(
        select(MonthlyEntityPosition).where(
            MonthlyEntityPosition.entity_id == entity_id,
            MonthlyEntityPosition.year == year,
            MonthlyEntityPosition.month == month,
        )
    ).first()


def _recalc_hybrid_invested(db: Session, *, entity_id: str, year: int, month: int) -> bool:
    position = _load_entity_position(db, entity_id=entity_id, year=year, month=month)
    if position is None:
        return False
    totals = sum_linked_asset_investments_eur(db, entity_id, year, month)
    position.invested_amount = float(totals["total_eur"])
    return True


def apply_auto_trades_to_hybrid_entities(
    db: Session,
    inserted_fills: list[dict],
    *,
    source: AutoTradeSource,
) -> HybridAutoAdjustResult:
    """Ajusta líquido por fill y recalcula invertido híbrido por entidad/mes afectados."""
    result = HybridAutoAdjustResult()
    if not inserted_fills:
        return result

    entities_to_recalc: set[tuple[str, int, int]] = set()

    for fill in inserted_fills:
        ym = _executed_year_month(fill)
        if ym is None:
            result.fills_skipped += 1
            result.skip_reasons.append(f"sin executed_at trade={fill.get('exchange_trade_id')}")
            continue

        year, month = ym
        asset_type_id = str(fill["asset_type_id"])
        asset = db.get(AssetType, asset_type_id)
        if asset is None:
            result.fills_skipped += 1
            result.skip_reasons.append(f"asset desconocido {asset_type_id}")
            continue

        if not asset.entity_id:
            result.fills_skipped += 1
            result.skip_reasons.append(f"asset {asset_type_id} sin entity_id")
            continue

        entity = db.get(Entity, asset.entity_id)
        if entity is None or entity.entity_type != EntityType.HYBRID:
            result.fills_skipped += 1
            result.skip_reasons.append(f"entidad no HYBRID para asset {asset_type_id}")
            continue

        if not _monthly_asset_row_exists(db, asset_type_id=asset_type_id, year=year, month=month):
            result.fills_skipped += 1
            result.skip_reasons.append(
                f"sin monthly_asset_investments {asset_type_id} {year}-{month:02d}"
            )
            continue

        position = _load_entity_position(db, entity_id=entity.id, year=year, month=month)
        if position is None:
            result.fills_skipped += 1
            result.skip_reasons.append(
                f"sin monthly_entity_positions {entity.id} {year}-{month:02d}"
            )
            continue

        delta_eur = _liquid_delta_eur(
            fill,
            currency=asset.currency,
            year=year,
            month=month,
            source=source,
        )
        if delta_eur is None:
            if source == "myinvestor" and Decimal(str(fill["asset_amount"])) < 0:
                logger.info(
                    "MyInvestor venta omitida en ajuste híbrido (TODO): trade=%s",
                    fill.get("exchange_trade_id"),
                )
            result.fills_skipped += 1
            result.skip_reasons.append(
                f"sin delta líquido trade={fill.get('exchange_trade_id')}"
            )
            continue

        liquid = Decimal(str(position.liquid_amount))
        position.liquid_amount = float((liquid + delta_eur).quantize(_MONEY))
        result.fills_liquid_adjusted += 1
        entities_to_recalc.add((entity.id, year, month))
        logger.info(
            "híbrida líquido entity=%s %s-%02d delta_eur=%s trade=%s",
            entity.id,
            year,
            month,
            delta_eur,
            fill.get("exchange_trade_id"),
        )

    for entity_id, year, month in sorted(entities_to_recalc):
        if _recalc_hybrid_invested(db, entity_id=entity_id, year=year, month=month):
            result.entities_recalculated += 1
            logger.info(
                "híbrida invertido recalculado entity=%s %s-%02d",
                entity_id,
                year,
                month,
            )

    if result.fills_liquid_adjusted or result.entities_recalculated:
        db.commit()

    return result
