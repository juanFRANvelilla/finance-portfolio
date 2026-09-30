"""Consolida ventas KuCoin del mismo activo y día en una fila de asset_sales."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


def kucoin_daily_sale_exchange_trade_id(asset_type_id: str, sale_date: date) -> str:
    return f"kucoin:daily-sale:{asset_type_id}:{sale_date.isoformat()}"


def build_daily_kucoin_sale_row(
    db: Session, asset_type_id: str, sale_date: date
) -> dict | None:
    """Agrega todas las ventas (tx con asset_amount < 0) del activo en ese día."""
    sells = db.execute(
        text(
            """
            SELECT asset_amount, invested_amount, fee_amount, executed_at
            FROM public.asset_transactions
            WHERE asset_type_id = :asset_type_id
              AND transaction_date = :sale_date
              AND asset_amount < 0
            ORDER BY executed_at NULLS LAST, id
            """
        ),
        {"asset_type_id": asset_type_id, "sale_date": sale_date},
    ).fetchall()

    if not sells:
        return None

    first_executed_at = sells[0].executed_at

    position_row = db.execute(
        text(
            """
            SELECT COALESCE(SUM(asset_amount), 0), COALESCE(SUM(invested_amount), 0)
            FROM public.asset_transactions
            WHERE asset_type_id = :asset_type_id
              AND (
                transaction_date < :sale_date
                OR (
                  transaction_date = :sale_date
                  AND executed_at IS NOT NULL
                  AND executed_at < :first_executed_at
                )
              )
            """
        ),
        {
            "asset_type_id": asset_type_id,
            "sale_date": sale_date,
            "first_executed_at": first_executed_at,
        },
    ).one()

    position_units = Decimal(str(position_row[0]))
    position_invested = Decimal(str(position_row[1]))

    if first_executed_at is None:
        position_row = db.execute(
            text(
                """
                SELECT COALESCE(SUM(asset_amount), 0), COALESCE(SUM(invested_amount), 0)
                FROM public.asset_transactions
                WHERE asset_type_id = :asset_type_id
                  AND transaction_date < :sale_date
                """
            ),
            {"asset_type_id": asset_type_id, "sale_date": sale_date},
        ).one()
        position_units = Decimal(str(position_row[0]))
        position_invested = Decimal(str(position_row[1]))

    if position_units <= 0:
        position_units = Decimal("0")
        position_invested = Decimal("0")

    running_units = position_units
    running_invested = position_invested

    total_units = Decimal("0")
    total_proceeds = Decimal("0")
    total_fee = Decimal("0")
    total_cost_basis = Decimal("0")

    for sell in sells:
        units_sold = abs(Decimal(str(sell.asset_amount)))
        proceeds = abs(Decimal(str(sell.invested_amount)))
        fee = Decimal(str(sell.fee_amount or 0))

        if running_units <= 0:
            avg_buy = Decimal("0")
        else:
            avg_buy = running_invested / running_units

        cost_basis = avg_buy * units_sold
        total_units += units_sold
        total_proceeds += proceeds
        total_fee += fee
        total_cost_basis += cost_basis

        running_units -= units_sold
        running_invested -= cost_basis

    if total_units <= 0:
        return None

    sale_price = (total_proceeds / total_units).quantize(Decimal("0.0001"))
    avg_buy_price = (total_cost_basis / total_units).quantize(Decimal("0.0001"))
    units_float = float(total_units.quantize(Decimal("0.00000001")))

    if position_units > 0:
        position_sold_pct = float(
            min(Decimal("100"), (total_units / position_units * Decimal("100"))).quantize(
                Decimal("0.0001")
            )
        )
    else:
        position_sold_pct = 100.0 if units_float > 0 else 0.0

    return {
        "asset_type_id": asset_type_id,
        "units": units_float,
        "sale_year": sale_date.year,
        "sale_month": sale_date.month,
        "sale_date": sale_date,
        "avg_buy_price": float(avg_buy_price),
        "sale_price": float(sale_price),
        "fee": float(total_fee.quantize(Decimal("0.0001"))),
        "position_sold_pct": position_sold_pct,
        "exchange_trade_id": kucoin_daily_sale_exchange_trade_id(asset_type_id, sale_date),
    }
