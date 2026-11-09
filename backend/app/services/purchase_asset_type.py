"""Crea el activo de una compra automática si el ticker todavía no existe.

MyInvestor busca por ticker (y, si no hay, por nombre exacto). KuCoin busca por
ticker del par y, si no hay, por el nombre de la divisa base, que es como ya
casa los fills. El activo nuevo queda ligado a la entidad híbrida del broker
para que el líquido baje con la lógica que ya aplica las compras.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.models.investment_category import InvestmentCategory
from app.myinvestor.trades.parse_trade import (
    ParsedMyInvestorTrade,
    amounts_for_asset_currency,
    is_purchase_side,
)

logger = logging.getLogger(__name__)

_ALLOWED_CURRENCIES = frozenset({"EUR", "USD"})
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")


def find_asset_by_name_and_entity(db: Session, name: str, entity_id: str) -> AssetType | None:
    key = " ".join((name or "").split()).upper()[:50]
    if not key or not entity_id:
        return None
    return db.scalars(
        select(AssetType).where(
            func.upper(AssetType.name) == key,
            AssetType.entity_id == entity_id,
        )
    ).first()


def create_trade_republic_asset(
    db: Session, *, name: str, ticker: str, currency: str
) -> AssetType | None:
    """Compra Trade Republic: activo nuevo ligado a esa entidad, ticker = symbol."""
    category_id = _trade_republic_category_id(db)
    if category_id is None:
        logger.error(
            "No se crea el activo Trade Republic %s: no hay categoría de acciones",
            name,
        )
        return None
    return _create_purchase_asset(
        db,
        ticker=ticker,
        name=name,
        currency=currency,
        entity_id=get_settings().trade_republic_entity_id,
        category_id=category_id,
        price_source="yahoo",
    )


def find_asset_type_by_ticker(db: Session, ticker: str) -> AssetType | None:
    key = (ticker or "").strip().upper()
    if not key:
        return None
    return db.scalars(select(AssetType).where(func.upper(AssetType.ticker) == key)).first()


def create_myinvestor_asset_for_purchase(
    db: Session, trade: ParsedMyInvestorTrade
) -> tuple[AssetType | None, bool]:
    """Compra MyInvestor sin ticker en catálogo: lo crea con el nombre y la divisa pagada.

    Devuelve `(activo, creado)`. `creado` es False si ya existía por ticker o por nombre.
    """
    if not is_purchase_side(trade.side):
        return None, False

    for candidate in (trade.ticker, trade.isin):
        existing = find_asset_type_by_ticker(db, candidate)
        if existing is not None:
            return existing, False

    by_name = _find_by_name(db, trade.instrument_name)
    if by_name is not None:
        logger.info(
            "Compra MyInvestor %s usa el activo existente '%s' (ticker %s)",
            trade.reference,
            by_name.name,
            by_name.ticker,
        )
        return by_name, False

    currency = _myinvestor_payment_currency(trade)
    if currency is None:
        logger.warning(
            "Compra MyInvestor %s sin divisa de pago EUR/USD (trade=%s, liquidación=%s); no se crea el activo",
            trade.reference,
            trade.trade_currency,
            trade.settlement_currency,
        )
        return None, False

    ticker = (trade.ticker or trade.isin or "").strip().upper()
    category_id = "fondos" if _ISIN_RE.match(ticker) else "stocks"
    price_source = None if _ISIN_RE.match(ticker) else "yahoo"
    created = _create_purchase_asset(
        db,
        ticker=ticker,
        name=trade.instrument_name or ticker,
        currency=currency,
        entity_id=get_settings().myinvestor_entity_id,
        category_id=category_id,
        price_source=price_source,
    )
    return created, created is not None


def ensure_kucoin_purchase_assets(
    db: Session,
    raw_fills: list[dict],
    asset_map: dict[str, str],
) -> int:
    """Registra en el mapa (y crea si falta) el activo de cada compra KuCoin.

    La divisa guardada es EUR: el fill ya convierte USDT→EUR antes de tocar el líquido.
    """
    created = 0
    for fill in raw_fills:
        side = str(fill.get("side", "")).upper()
        if side != "BUY":
            continue
        parts = str(fill.get("symbol", "")).upper().split("-")
        if len(parts) != 2:
            continue
        base, quote = parts
        if not base or base == "USDT" or base in asset_map:
            continue
        if quote not in {"EUR", "USDT"}:
            continue

        pair = f"{base}-EUR" if quote == "USDT" else f"{base}-{quote}"
        existing = find_asset_type_by_ticker(db, pair) or find_asset_type_by_ticker(db, base)
        if existing is None:
            existing = _find_by_name(db, base)
        if existing is not None:
            asset_map[base] = str(existing.id)
            continue

        asset = _create_purchase_asset(
            db,
            ticker=pair,
            name=base,
            currency="EUR",
            entity_id=get_settings().kucoin_entity_id,
            category_id="crypto",
            price_source="kucoin",
        )
        if asset is None:
            continue
        asset_map[base] = str(asset.id)
        created += 1
    return created


def _myinvestor_payment_currency(trade: ParsedMyInvestorTrade) -> str | None:
    for raw in (trade.settlement_currency, trade.trade_currency):
        currency = (raw or "").upper()
        if currency not in _ALLOWED_CURRENCIES:
            continue
        if amounts_for_asset_currency(trade, currency) is not None:
            return currency
    return None


def _find_by_name(db: Session, name: str) -> AssetType | None:
    key = " ".join((name or "").split()).upper()
    if not key:
        return None
    return db.scalars(select(AssetType).where(func.upper(AssetType.name) == key[:50])).first()


def _trade_republic_category_id(db: Session) -> str | None:
    """Acciones de Trade Republic. En PRE/PRO el id es 'acciones', no 'stocks'."""
    for candidate in ("acciones", "stocks"):
        if db.get(InvestmentCategory, candidate) is not None:
            return candidate
    return db.scalars(
        select(InvestmentCategory.id).where(func.lower(InvestmentCategory.name).like("%accion%"))
    ).first()


def _category_id(db: Session, preferred: str) -> str | None:
    if db.get(InvestmentCategory, preferred) is not None:
        return preferred
    return db.scalars(
        select(InvestmentCategory.id).order_by(InvestmentCategory.display_order, InvestmentCategory.id)
    ).first()


def _create_purchase_asset(
    db: Session,
    *,
    ticker: str,
    name: str,
    currency: str,
    entity_id: str,
    category_id: str,
    price_source: str | None,
) -> AssetType | None:
    entity = db.get(Entity, entity_id)
    if entity is None or entity.entity_type != EntityType.HYBRID:
        logger.error(
            "No se crea el activo %s: la entidad %r no existe o no es HYBRID",
            ticker,
            entity_id,
        )
        return None

    resolved_category = _category_id(db, category_id)
    if resolved_category is None:
        logger.error("No se crea el activo %s: no hay categorías de inversión", ticker)
        return None

    clean_ticker = ticker.strip().upper()[:20]
    clean_name = " ".join(name.split())[:50] or clean_ticker
    if not clean_ticker:
        return None

    next_order = db.scalar(
        select(func.coalesce(func.max(AssetType.display_order), 0)).where(
            AssetType.category_id == resolved_category
        )
    )
    asset = AssetType(
        category_id=resolved_category,
        name=clean_name,
        ticker=clean_ticker,
        currency=currency,
        display_order=int(next_order or 0) + 1,
        entity_id=entity_id,
        price_source=price_source,
        is_active=True,
    )
    db.add(asset)
    db.flush()
    logger.info(
        "Activo creado por compra ticker=%s name=%s currency=%s entity=%s category=%s",
        asset.ticker,
        asset.name,
        asset.currency,
        asset.entity_id,
        asset.category_id,
    )
    return asset
