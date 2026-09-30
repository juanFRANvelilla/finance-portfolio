"""Consultas e inserciones sobre asset_transactions."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
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


@dataclass(frozen=True)
class AssetMatch:
    asset_type_id: str
    currency: str
    entity_id: str | None


def load_asset_match_index(db: Session) -> dict[str, AssetMatch]:
    """Índice ticker/name en mayúsculas → activo, para casar operaciones de broker.

    Si varias filas comparten clave, se prefiere `entity_id='myinvestor'`.
    Si la clave sigue siendo ambigua, no se incluye.
    """
    rows = db.execute(
        text(
            "SELECT id, name, ticker, currency, entity_id FROM public.asset_types"
        )
    ).fetchall()

    grouped: dict[str, list[AssetMatch]] = defaultdict(list)
    for row in rows:
        match = AssetMatch(
            asset_type_id=str(row.id),
            currency=(row.currency or "EUR").upper(),
            entity_id=row.entity_id,
        )
        keys = set()
        if row.ticker:
            keys.add(str(row.ticker).upper())
        if row.name:
            keys.add(str(row.name).upper())
        for key in keys:
            grouped[key].append(match)

    resolved: dict[str, AssetMatch] = {}
    for key, matches in grouped.items():
        unique = {item.asset_type_id: item for item in matches}
        candidates = list(unique.values())
        preferred = [item for item in candidates if item.entity_id == "myinvestor"]
        if len(preferred) == 1:
            resolved[key] = preferred[0]
        elif len(candidates) == 1:
            resolved[key] = candidates[0]
    return resolved


def sum_position_by_asset_type_ids(
    db: Session, asset_type_ids: list[str]
) -> dict[str, tuple[Decimal, Decimal]]:
    """Suma (unidades, invested_amount) acumulada por activo en asset_transactions."""
    if not asset_type_ids:
        return {}

    rows = db.execute(
        text(
            """
            SELECT asset_type_id::text,
                   COALESCE(SUM(asset_amount), 0),
                   COALESCE(SUM(invested_amount), 0)
            FROM public.asset_transactions
            WHERE asset_type_id::text = ANY(:ids)
            GROUP BY asset_type_id
            """
        ),
        {"ids": asset_type_ids},
    ).fetchall()

    return {
        str(row[0]): (Decimal(str(row[1])), Decimal(str(row[2])))
        for row in rows
    }


def load_kucoin_asset_name_map(db: Session) -> dict[str, str]:
    """Mapea name (upper) → asset_type_id para casar la divisa base de fills KuCoin (p.ej. BTC, ETH)."""
    rows = db.execute(
        text(
            "SELECT id, name FROM public.asset_types "
            "WHERE price_source = 'kucoin' AND name IS NOT NULL"
        )
    ).fetchall()
    return {row.name.upper(): str(row.id) for row in rows}


def insert_transactions_batch(db: Session, fills: list[dict]) -> tuple[int, int, list[dict]]:
    """Inserta fills con ON CONFLICT (exchange_trade_id) DO NOTHING.

    Devuelve (insertados, omitidos_por_conflicto, fills_insertados).
    `fills_insertados` es el subconjunto de `fills` que sí se llegó a insertar
    (los duplicados por `exchange_trade_id` no salen en esa lista). Se usa para
    actualizar monthly_asset_investments solo con lo que es realmente nuevo.
    """
    import uuid

    insertados = 0
    omitidos = 0
    fills_insertados: list[dict] = []

    for fill in fills:
        result = db.execute(
            text(
                """
                INSERT INTO public.asset_transactions
                    (id, asset_type_id, transaction_date, executed_at, invested_amount,
                     asset_amount, execution_price, fee_amount, exchange_trade_id)
                VALUES
                    (:id, :asset_type_id, :transaction_date, :executed_at, :invested_amount,
                     :asset_amount, :execution_price, :fee_amount, :exchange_trade_id)
                ON CONFLICT (exchange_trade_id) DO NOTHING
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "asset_type_id": fill["asset_type_id"],
                "transaction_date": fill["transaction_date"],
                "executed_at": fill.get("executed_at"),
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
            fills_insertados.append(fill)

    db.commit()
    return insertados, omitidos, fills_insertados
