"""Inserciones idempotentes en asset_sales (p. ej. ventas sincronizadas desde KuCoin)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_kucoin_daily_asset_sale(db: Session, row: dict) -> bool:
    """Inserta o actualiza la venta diaria consolidada. Devuelve True si insertó."""
    result = db.execute(
        text(
            """
            INSERT INTO public.asset_sales
                (id, asset_type_id, units, sale_year, sale_month, sale_date,
                 avg_buy_price, sale_price, fee, position_sold_pct, exchange_trade_id)
            VALUES
                (:id, :asset_type_id, :units, :sale_year, :sale_month, :sale_date,
                 :avg_buy_price, :sale_price, :fee, :position_sold_pct, :exchange_trade_id)
            ON CONFLICT (exchange_trade_id) DO UPDATE SET
                units = EXCLUDED.units,
                sale_year = EXCLUDED.sale_year,
                sale_month = EXCLUDED.sale_month,
                sale_date = EXCLUDED.sale_date,
                avg_buy_price = EXCLUDED.avg_buy_price,
                sale_price = EXCLUDED.sale_price,
                fee = EXCLUDED.fee,
                position_sold_pct = EXCLUDED.position_sold_pct
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "asset_type_id": row["asset_type_id"],
            "units": row["units"],
            "sale_year": row["sale_year"],
            "sale_month": row["sale_month"],
            "sale_date": row["sale_date"],
            "avg_buy_price": row["avg_buy_price"],
            "sale_price": row["sale_price"],
            "fee": row["fee"],
            "position_sold_pct": row["position_sold_pct"],
            "exchange_trade_id": row["exchange_trade_id"],
        },
    )
    return result.rowcount == 1


def upsert_kucoin_daily_asset_sales_batch(db: Session, rows: list[dict]) -> tuple[int, int]:
    """Devuelve (insertadas, actualizadas)."""
    inserted = 0
    updated = 0
    for row in rows:
        if upsert_kucoin_daily_asset_sale(db, row):
            inserted += 1
        else:
            updated += 1
    return inserted, updated
