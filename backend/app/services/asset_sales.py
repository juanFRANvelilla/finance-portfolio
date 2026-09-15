"""Contexto de posición y registro de ventas en asset_sales."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset_sale import AssetSale
from app.models.asset_type import AssetType
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.services.asset_transactions import transaction_totals_by_asset_type
from app.services.fx_converter import eur_to_native


def _to_decimal(value: Decimal | float | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round4(value: Decimal | float | int) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.0001")))


def _round8(value: Decimal | float | int) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.00000001")))


def _units_sold_through_period(
    db: Session, asset_type_id: UUID, year: int, month: int
) -> Decimal:
    stmt = select(func.coalesce(func.sum(AssetSale.units), 0)).where(
        AssetSale.asset_type_id == asset_type_id,
        (AssetSale.sale_year < year)
        | ((AssetSale.sale_year == year) & (AssetSale.sale_month <= month)),
    )
    return Decimal(str(db.scalar(stmt) or 0))


def _position_at_month(
    db: Session, asset: AssetType, year: int, month: int
) -> tuple[float, float]:
    """Devuelve (unidades de posición, coste total en divisa nativa)."""
    saved = db.scalars(
        select(MonthlyAssetInvestment).where(
            MonthlyAssetInvestment.year == year,
            MonthlyAssetInvestment.month == month,
            MonthlyAssetInvestment.asset_type_id == asset.id,
        )
    ).first()

    tx_totals = transaction_totals_by_asset_type(db, [asset.id], year=year, month=month).get(asset.id)

    if saved is not None and saved.units is not None and Decimal(str(saved.units)) > 0:
        units = Decimal(str(saved.units))
        cost_native = Decimal(str(saved.amount))
        return _round8(units), _round4(cost_native)

    if tx_totals and Decimal(str(tx_totals.get("asset_amount", 0))) > 0:
        units = Decimal(str(tx_totals["asset_amount"]))
        invested_eur = Decimal(str(tx_totals.get("invested_amount_eur", 0)))
        cost_native = Decimal(str(eur_to_native(float(invested_eur), asset.currency, year, month)))
        return _round8(units), _round4(cost_native)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El activo no tiene títulos registrados para este mes",
    )


def get_sale_context(db: Session, asset_type_id: UUID, year: int, month: int) -> dict:
    asset = db.get(AssetType, asset_type_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")

    position_units, cost_native = _position_at_month(db, asset, year, month)
    position_dec = Decimal(str(position_units))
    if position_dec <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El activo no tiene posición vendible en este mes",
        )

    sold = _units_sold_through_period(db, asset_type_id, year, month)
    available = position_dec - sold
    if available <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No quedan títulos disponibles para vender (ya registradas ventas previas)",
        )

    cost_dec = Decimal(str(cost_native))
    avg_buy_price = _round4(cost_dec / position_dec)

    return {
        "asset_type_id": asset.id,
        "asset_name": asset.name,
        "currency": asset.currency,
        "year": year,
        "month": month,
        "position_units": position_units,
        "available_units": _round8(available),
        "avg_buy_price": avg_buy_price,
        "cost_basis_total": _round4(cost_native),
    }


def preview_sale(
    db: Session,
    asset_type_id: UUID,
    year: int,
    month: int,
    *,
    units: float,
    sale_price: float,
) -> dict:
    context = get_sale_context(db, asset_type_id, year, month)
    units_dec = Decimal(str(units))
    available = Decimal(str(context["available_units"]))
    if units_dec <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Las unidades deben ser mayores que 0")
    if units_dec > available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Solo puedes vender hasta {context['available_units']} títulos",
        )

    avg = Decimal(str(context["avg_buy_price"]))
    sale = Decimal(str(sale_price))
    profit = (sale - avg) * units_dec
    profit_pct = ((sale - avg) / avg * Decimal("100")) if avg > 0 else Decimal("0")
    share_pct = (units_dec / Decimal(str(context["position_units"])) * Decimal("100")) if context[
        "position_units"
    ] > 0 else Decimal("0")

    return {
        "units": _round8(units_dec),
        "sale_price": _round4(sale),
        "avg_buy_price": float(avg),
        "profit": _round4(profit),
        "profit_percentage": _round4(profit_pct),
        "position_share_pct": _round4(share_pct),
    }


def create_asset_sale(
    db: Session,
    asset_type_id: UUID,
    year: int,
    month: int,
    *,
    units: float,
    sale_price: float,
) -> AssetSale:
    preview = preview_sale(db, asset_type_id, year, month, units=units, sale_price=sale_price)
    sale = AssetSale(
        asset_type_id=asset_type_id,
        units=preview["units"],
        sale_year=year,
        sale_month=month,
        avg_buy_price=preview["avg_buy_price"],
        sale_price=preview["sale_price"],
    )
    db.add(sale)
    db.commit()
    db.refresh(sale)
    return sale
