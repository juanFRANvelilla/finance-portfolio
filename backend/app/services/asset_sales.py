"""Contexto de posición y registro de ventas en asset_sales."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.asset_sale import AssetSale
from app.models.asset_transaction import AssetTransaction
from app.models.asset_type import AssetType
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.services.asset_transactions import transaction_totals_by_asset_type
from app.services.fx_converter import amount_to_eur, eur_to_native


def _to_decimal(value: Decimal | float | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round4(value: Decimal | float | int) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.0001")))


def _round8(value: Decimal | float | int) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.00000001")))


def has_asset_sale_in_month(db: Session, asset_type_id: UUID, year: int, month: int) -> bool:
    stmt = (
        select(AssetSale.id)
        .where(
            AssetSale.asset_type_id == asset_type_id,
            AssetSale.sale_year == year,
            AssetSale.sale_month == month,
        )
        .limit(1)
    )
    return db.scalar(stmt) is not None


def asset_type_ids_with_sale_in_month(
    db: Session, asset_type_ids: list[UUID], year: int, month: int
) -> set[UUID]:
    if not asset_type_ids:
        return set()
    stmt = select(AssetSale.asset_type_id).where(
        AssetSale.asset_type_id.in_(asset_type_ids),
        AssetSale.sale_year == year,
        AssetSale.sale_month == month,
    )
    return set(db.scalars(stmt).all())


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

    # Títulos según el registro mensual / ledger; tras una venta el usuario actualiza a mano.
    available = position_dec
    if available <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El activo no tiene títulos registrados para este mes",
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
        "position_cost_basis": _round4(cost_native),
        "has_sale_this_month": has_asset_sale_in_month(db, asset_type_id, year, month),
    }


def _resolve_cost_basis(
    *,
    units: Decimal,
    pmp_avg_price: Decimal,
    position_cost_basis: Decimal,
    cost_basis: float | None,
) -> tuple[Decimal, Decimal]:
    """Devuelve (cost_basis imputado, avg_buy_price unitario)."""
    if cost_basis is not None:
        cost_dec = Decimal(str(cost_basis))
        if cost_dec <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El coste de adquisición imputado debe ser mayor que 0",
            )
        if cost_dec > position_cost_basis:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El coste imputado supera el capital total de la posición",
            )
        avg = cost_dec / units
        return cost_dec, avg

    cost_dec = pmp_avg_price * units
    return cost_dec, pmp_avg_price


def _sale_metrics(
    units: Decimal, sale_price: Decimal, fee: Decimal, cost_basis: Decimal
) -> dict:
    net_liquidity = sale_price * units - fee
    profit = net_liquidity - cost_basis
    avg = cost_basis / units if units > 0 else Decimal("0")
    profit_pct = (profit / cost_basis * Decimal("100")) if cost_basis > 0 else Decimal("0")
    return {
        "avg_buy_price": _round4(avg),
        "net_liquidity": _round4(net_liquidity),
        "cost_basis": _round4(cost_basis),
        "gross_profit": _round4(profit + fee),
        "profit": _round4(profit),
        "profit_percentage": _round4(profit_pct),
    }


def preview_sale(
    db: Session,
    asset_type_id: UUID,
    year: int,
    month: int,
    *,
    units: float,
    sale_price: float,
    fee: float = 0,
    cost_basis: float | None = None,
) -> dict:
    context = get_sale_context(db, asset_type_id, year, month)
    units_dec = Decimal(str(units))
    available = Decimal(str(context["available_units"]))
    if units_dec <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Las unidades deben ser mayores que 0")
    position_units = Decimal(str(context["position_units"]))
    if units_dec > position_units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Solo puedes vender hasta {context['position_units']} títulos (según el registro del mes)",
        )

    sale = Decimal(str(sale_price))
    fee_dec = Decimal(str(fee))
    if fee_dec < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La comisión no puede ser negativa")

    position_cost = Decimal(str(context["position_cost_basis"]))
    pmp_avg = Decimal(str(context["avg_buy_price"]))
    cost_dec, avg = _resolve_cost_basis(
        units=units_dec,
        pmp_avg_price=pmp_avg,
        position_cost_basis=position_cost,
        cost_basis=cost_basis,
    )
    metrics = _sale_metrics(units_dec, sale, fee_dec, cost_dec)
    share_pct = (units_dec / Decimal(str(context["position_units"])) * Decimal("100")) if context[
        "position_units"
    ] > 0 else Decimal("0")

    return {
        "units": _round8(units_dec),
        "sale_price": _round4(sale),
        "fee": _round4(fee_dec),
        "avg_buy_price": metrics["avg_buy_price"],
        "cost_basis": metrics["cost_basis"],
        "net_liquidity": metrics["net_liquidity"],
        "gross_profit": metrics["gross_profit"],
        "profit": metrics["profit"],
        "profit_percentage": metrics["profit_percentage"],
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
    fee: float = 0,
    cost_basis: float | None = None,
    sale_date: date,
) -> AssetSale:
    asset = db.get(AssetType, asset_type_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")

    preview = preview_sale(
        db,
        asset_type_id,
        year,
        month,
        units=units,
        sale_price=sale_price,
        fee=fee,
        cost_basis=cost_basis,
    )

    sale_id = uuid.uuid4()
    sale = AssetSale(
        id=sale_id,
        asset_type_id=asset_type_id,
        units=preview["units"],
        sale_year=year,
        sale_month=month,
        sale_date=sale_date,
        avg_buy_price=preview["avg_buy_price"],
        sale_price=preview["sale_price"],
        fee=preview["fee"],
    )
    db.add(sale)

    cost_basis_native = float(preview["cost_basis"])
    invested_eur = -amount_to_eur(cost_basis_native, asset.currency, year, month)

    db.add(
        AssetTransaction(
            asset_type_id=asset_type_id,
            transaction_date=sale_date,
            invested_amount=invested_eur,
            asset_amount=-float(preview["units"]),
            execution_price=float(preview["sale_price"]),
            fee_amount=float(preview["fee"]),
            exchange_trade_id=f"manual-sale-{sale_id}",
        )
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(sale)
    return sale


def list_asset_sales(db: Session) -> dict:
    """Todas las ventas (histórico) y beneficio neto acumulado en EUR."""
    stmt = (
        select(AssetSale)
        .options(joinedload(AssetSale.asset_type))
        .order_by(
            AssetSale.sale_year.desc(),
            AssetSale.sale_month.desc(),
            AssetSale.sale_date.desc().nullslast(),
            AssetSale.created_at.desc(),
        )
    )
    sales = db.scalars(stmt).unique().all()

    total_profit_eur = Decimal("0")
    items: list[dict] = []

    for sale in sales:
        asset = sale.asset_type
        currency = asset.currency if asset else "EUR"
        name = asset.name if asset else "—"
        profit_native = Decimal(str(sale.profit))
        profit_eur = Decimal(str(amount_to_eur(float(profit_native), currency, sale.sale_year, sale.sale_month)))
        total_profit_eur += profit_eur

        items.append(
            {
                "id": sale.id,
                "asset_type_id": sale.asset_type_id,
                "asset_name": name,
                "currency": currency,
                "sale_year": sale.sale_year,
                "sale_month": sale.sale_month,
                "sale_date": sale.sale_date,
                "units": _round8(sale.units),
                "sale_price": _round4(sale.sale_price),
                "profit": _round4(profit_native),
                "profit_percentage": _round4(sale.profit_percentage),
                "profit_eur": _round4(profit_eur),
            }
        )

    return {
        "total_profit_eur": _round4(total_profit_eur),
        "sales": items,
    }
