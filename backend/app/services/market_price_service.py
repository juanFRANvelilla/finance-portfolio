"""Orquestador de precios de mercado en vivo con caché en memoria y persistencia a disco."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT
from app.models.asset_type import AssetType
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.kucoin_provider import KucoinMarketDataProvider
from app.services.market_data.yahoo_provider import YahooMarketDataProvider

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 45
CACHE_FILE_PATH = BACKEND_ROOT / ".cache" / "market_prices_cache.json"


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

    - Mantiene una caché en memoria y la persiste en disco para que nunca empiece vacía.
    - Resuelve precios concurrentemente mediante un ThreadPoolExecutor.
    - En peticiones normales devuelve inmediatamente el último valor conocido para no bloquear
      la interfaz, mientras el proceso en segundo plano mantiene los precios actualizados.
    """

    def __init__(self, cache_file_path: Path | None = None) -> None:
        self._providers: dict[str, MarketDataProvider] = {
            "kucoin": KucoinMarketDataProvider(),
            "yahoo": YahooMarketDataProvider(),
        }
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = threading.Lock()
        self._cache_file = cache_file_path or CACHE_FILE_PATH
        self._load_cache_from_disk()

    def _load_cache_from_disk(self) -> None:
        try:
            if not self._cache_file.exists():
                return
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = {}
            for key, val in data.items():
                if ":" in key and isinstance(val, dict):
                    source, ticker = key.split(":", 1)
                    loaded[(source, ticker)] = _CacheEntry(
                        price=float(val["price"]),
                        currency=str(val["currency"]),
                        fetched_at=float(val.get("fetched_at", 0.0)),
                    )
            with self._lock:
                self._cache.update(loaded)
            logger.info("Caché de precios cargada desde disco: %s entradas", len(loaded))
        except Exception as exc:
            logger.warning("No se pudo cargar la caché de precios desde disco: %s", exc)

    def _save_cache_to_disk(self) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                dump = {
                    f"{src}:{ticker}": {
                        "price": entry.price,
                        "currency": entry.currency,
                        "fetched_at": entry.fetched_at,
                    }
                    for (src, ticker), entry in self._cache.items()
                }
            temp_file = self._cache_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(dump, f, indent=2)
            temp_file.replace(self._cache_file)
        except Exception as exc:
            logger.warning("No se pudo guardar la caché de precios en disco: %s", exc)

    def get_prices(self, db: Session, *, force_refresh: bool = False) -> list[MarketPriceItem]:
        rows = db.execute(
            select(AssetType.id, AssetType.ticker, AssetType.price_source).where(
                AssetType.ticker.is_not(None),
                AssetType.price_source.is_not(None),
            )
        ).all()

        if force_refresh:
            return self.refresh_all_prices(db)

        # Si no es force_refresh, resolvemos con los datos de caché disponibles.
        missing_tasks: list[tuple[str, str]] = []
        with self._lock:
            for _, ticker, price_source in rows:
                if (price_source, ticker) not in self._cache:
                    missing_tasks.append((price_source, ticker))

        # Si hay activos nuevos sin ningún dato previo, los consultamos concurrentemente.
        if missing_tasks:
            self._fetch_concurrently(missing_tasks)

        items: list[MarketPriceItem] = []
        with self._lock:
            for asset_type_id, ticker, price_source in rows:
                entry = self._cache.get((price_source, ticker))
                if entry is None:
                    continue
                items.append(
                    MarketPriceItem(
                        asset_type_id=str(asset_type_id),
                        ticker=ticker,
                        price=entry.price,
                        currency=entry.currency,
                        updated_at=datetime.fromtimestamp(entry.fetched_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                )
        return items

    def refresh_all_prices(self, db: Session) -> list[MarketPriceItem]:
        """Consulta concurrentemente todos los activos configurados y refresca la caché."""
        rows = db.execute(
            select(AssetType.id, AssetType.ticker, AssetType.price_source).where(
                AssetType.ticker.is_not(None),
                AssetType.price_source.is_not(None),
            )
        ).all()

        unique_tasks = list({(price_source, ticker) for _, ticker, price_source in rows})
        if unique_tasks:
            self._fetch_concurrently(unique_tasks)

        items: list[MarketPriceItem] = []
        with self._lock:
            for asset_type_id, ticker, price_source in rows:
                entry = self._cache.get((price_source, ticker))
                if entry is None:
                    continue
                items.append(
                    MarketPriceItem(
                        asset_type_id=str(asset_type_id),
                        ticker=ticker,
                        price=entry.price,
                        currency=entry.currency,
                        updated_at=datetime.fromtimestamp(entry.fetched_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                )
        return items

    def _fetch_concurrently(self, tasks: list[tuple[str, str]]) -> None:
        """Descarga en paralelo precios de proveedores externos sin bloquear secuencialmente."""
        def fetch_one(src: str, tck: str) -> tuple[str, str, float, str, float] | None:
            provider = self._providers.get(src)
            if provider is None:
                return None
            try:
                quote = provider.get_price(tck)
                return (src, tck, float(quote["price"]), str(quote["currency"]), time.time())
            except Exception as exc:
                logger.warning("No se pudo obtener precio de '%s' vía %s: %s", tck, src, exc)
                return None

        results: list[tuple[str, str, float, str, float]] = []
        with ThreadPoolExecutor(max_workers=min(len(tasks), 6), thread_name_prefix="market-price-fetch") as executor:
            future_to_task = {executor.submit(fetch_one, src, tck): (src, tck) for src, tck in tasks}
            for future in as_completed(future_to_task):
                try:
                    res = future.result()
                    if res is not None:
                        results.append(res)
                except Exception as exc:
                    logger.warning("Excepción en fetch de precio: %s", exc)

        if results:
            with self._lock:
                for src, tck, price, currency, fetched_at in results:
                    self._cache[(src, tck)] = _CacheEntry(price=price, currency=currency, fetched_at=fetched_at)
            self._save_cache_to_disk()

    def invalidate_ticker(self, price_source: str | None, ticker: str | None) -> None:
        """Elimina la entrada de caché de un ticker (p. ej. tras editar un activo)."""
        if not price_source or not ticker:
            return
        with self._lock:
            self._cache.pop((price_source, ticker), None)
        self._save_cache_to_disk()


# Instancia única a nivel de módulo: la caché en memoria debe compartirse entre requests.
market_price_service = MarketPriceService()


def run_scheduled_market_prices_refresh() -> int:
    """Ejecutado periódicamente por APScheduler en segundo plano."""
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        updated = market_price_service.refresh_all_prices(db)
        return len(updated)
