"""Consolida ventas KuCoin del mismo activo y día en una fila de asset_sales."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


def kucoin_daily_sale_exchange_trade_id(asset_type_id: str, sale_date: date) -> str:
    return f"kucoin:daily-sale:{asset_type_id}:{sale_date.isoformat()}"


@dataclass(frozen=True)
class _SellSlice:
    asset_amount: Decimal
    gross_proceeds: Decimal
    fee_amount: Decimal


def aggregate_daily_kucoin_sale(
    *,
    asset_type_id: str,
    sale_date: date,
    sells: list[_SellSlice],
    position_units_before: Decimal,
    position_invested_before: Decimal,
) -> dict | None:
    """Consolida varias ventas del mismo activo en el mismo día (sin acceso a BD)."""
    if not sells:
        return None

    running_units = position_units_before
    running_invested = position_invested_before

    total_units = Decimal("0")
    total_proceeds = Decimal("0")
    total_fee = Decimal("0")
    total_cost_basis = Decimal("0")

    for sell in sells:
        units_sold = abs(sell.asset_amount)
        proceeds = sell.gross_proceeds
        fee = sell.fee_amount

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

    if position_units_before > 0:
        position_sold_pct = float(
            min(
                Decimal("100"),
                (total_units / position_units_before * Decimal("100")),
            ).quantize(Decimal("0.0001"))
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
        "net_liquidity": float((total_proceeds - total_fee).quantize(Decimal("0.0001"))),
        "position_sold_pct": position_sold_pct,
        "exchange_trade_id": kucoin_daily_sale_exchange_trade_id(asset_type_id, sale_date),
    }


def build_daily_kucoin_sale_row(
    db: Session, asset_type_id: str, sale_date: date
) -> dict | None:
    """Agrega todas las ventas (tx con asset_amount < 0) del activo en ese día."""
    sells = db.execute(
        text(
            """
            SELECT asset_amount, execution_price, fee_amount, executed_at
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

    slices = []
    for sell in sells:
        units = abs(Decimal(str(sell.asset_amount)))
        price = Decimal(str(sell.execution_price or 0))
        gross = (units * price).quantize(Decimal("0.00000001"))
        slices.append(
            _SellSlice(
                asset_amount=Decimal(str(sell.asset_amount)),
                gross_proceeds=gross,
                fee_amount=Decimal(str(sell.fee_amount or 0)),
            )
        )

    return aggregate_daily_kucoin_sale(
        asset_type_id=asset_type_id,
        sale_date=sale_date,
        sells=slices,
        position_units_before=position_units,
        position_invested_before=position_invested,
    )
