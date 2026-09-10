"""Orquestador de precios de mercado en vivo con caché en memoria (TTL)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset_type import AssetType
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.kucoin_provider import KucoinMarketDataProvider
from app.services.market_data.yahoo_provider import YahooMarketDataProvider

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 45


@dataclass(frozen=True)
class MarketPriceItem:
    asset_type_id: str
    ticker: str
    price: float
    currency: str
    updated_at: str


@dataclass
class _CacheEntry:
    price: float
    currency: str
    fetched_at: float


class MarketPriceService:
    """Consulta `asset_types` con ticker + price_source y despacha a cada proveedor.

    Cachea en memoria por (price_source, ticker) durante `CACHE_TTL_SECONDS` para no
    saturar las APIs externas en llamadas consecutivas (polling del frontend).
    Si un ticker falla y hay un valor cacheado previo (aunque esté caducado), se devuelve
    ese último valor conocido en vez de romper la respuesta completa.
    """

    def __init__(self) -> None:
        self._providers: dict[str, MarketDataProvider] = {
            "kucoin": KucoinMarketDataProvider(),
            "yahoo": YahooMarketDataProvider(),
        }
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = threading.Lock()

    def get_prices(self, db: Session, *, force_refresh: bool = False) -> list[MarketPriceItem]:
        rows = db.execute(
            select(AssetType.id, AssetType.ticker, AssetType.price_source).where(
                AssetType.ticker.is_not(None),
                AssetType.price_source.is_not(None),
            )
        ).all()

        items: list[MarketPriceItem] = []
        for asset_type_id, ticker, price_source in rows:
            provider = self._providers.get(price_source)
            if provider is None:
                logger.warning("price_source '%s' desconocido para ticker '%s'; se omite.", price_source, ticker)
                continue

            resolved = self._get_price_cached(provider, price_source, ticker, force_refresh=force_refresh)
            if resolved is None:
                continue

            price, currency, fetched_at = resolved
            items.append(
                MarketPriceItem(
                    asset_type_id=str(asset_type_id),
                    ticker=ticker,
                    price=price,
                    currency=currency,
                    updated_at=datetime.fromtimestamp(fetched_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
        return items

    def invalidate_ticker(self, price_source: str | None, ticker: str | None) -> None:
        """Elimina la entrada de caché de un ticker (p. ej. tras editar un activo)."""
        if not price_source or not ticker:
            return
        with self._lock:
            self._cache.pop((price_source, ticker), None)

    def _get_price_cached(
        self,
        provider: MarketDataProvider,
        price_source: str,
        ticker: str,
        *,
        force_refresh: bool = False,
    ) -> tuple[float, str, float] | None:
        cache_key = (price_source, ticker)
        now = time.time()

        with self._lock:
            cached = self._cache.get(cache_key)

        if (
            not force_refresh
            and cached is not None
            and (now - cached.fetched_at) < CACHE_TTL_SECONDS
        ):
            return cached.price, cached.currency, cached.fetched_at

        try:
            quote = provider.get_price(ticker)
            price = float(quote["price"])
            currency = str(quote["currency"])
        except Exception as exc:
            logger.warning("No se pudo obtener precio de '%s' vía %s: %s", ticker, price_source, exc)
            if cached is not None:
                return cached.price, cached.currency, cached.fetched_at
            return None

        entry = _CacheEntry(price=price, currency=currency, fetched_at=now)
        with self._lock:
            self._cache[cache_key] = entry
        return entry.price, entry.currency, entry.fetched_at


# Instancia única a nivel de módulo: la caché en memoria debe compartirse entre requests.
market_price_service = MarketPriceService()
