"""Consultas e inserciones sobre asset_transactions."""

from datetime import date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.asset_transaction import AssetTransaction

FALLBACK_SYNC_START = datetime(2025, 11, 20)


def get_max_transaction_date(db: Session) -> date | None:
    """Devuelve la fecha más reciente registrada en asset_transactions, o None si está vacía."""
    return db.scalar(select(func.max(AssetTransaction.transaction_date)))


def resolve_sync_start_datetime(db: Session) -> datetime:
    """Punto de partida para sincronizar KuCoin: MAX(transaction_date) o fallback fijo."""
    max_date = get_max_transaction_date(db)
    if max_date is None:
        return FALLBACK_SYNC_START
    return datetime.combine(max_date, datetime.min.time())


def load_exchange_ticker_map(db: Session) -> dict[str, str]:
    """Mapea exchange_ticker (upper) → asset_type_id (str) desde asset_types."""
    rows = db.execute(
        text(
            "SELECT id, exchange_ticker FROM public.asset_types "
            "WHERE exchange_ticker IS NOT NULL"
        )
    ).fetchall()
    return {row.exchange_ticker.upper(): str(row.id) for row in rows}


def insert_transactions_batch(db: Session, fills: list[dict]) -> tuple[int, int]:
    """Inserta fills con ON CONFLICT (exchange_trade_id) DO NOTHING.

    Devuelve (insertados, omitidos_por_conflicto).
    """
    import uuid

    insertados = 0
    omitidos = 0

    for fill in fills:
        result = db.execute(
            text(
                """
                INSERT INTO public.asset_transactions
                    (id, asset_type_id, transaction_date, invested_amount,
                     asset_amount, execution_price, fee_amount, exchange_trade_id)
                VALUES
                    (:id, :asset_type_id, :transaction_date, :invested_amount,
                     :asset_amount, :execution_price, :fee_amount, :exchange_trade_id)
                ON CONFLICT (exchange_trade_id) DO NOTHING
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "asset_type_id": fill["asset_type_id"],
                "transaction_date": fill["transaction_date"],
                "invested_amount": fill["invested_amount"],
                "asset_amount": fill["asset_amount"],
                "execution_price": fill["execution_price"],
                "fee_amount": fill["fee_amount"],
                "exchange_trade_id": fill["exchange_trade_id"],
            },
        )
        if result.rowcount == 0:
            omitidos += 1
        else:
            insertados += 1

    db.commit()
    return insertados, omitidos
