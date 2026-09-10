"""Proveedor de precios de mercado en vivo vía Yahoo Finance (yfinance)."""

from __future__ import annotations

import logging

import yfinance as yf

from app.services.market_data.base import MarketDataProvider, PriceQuote

logger = logging.getLogger(__name__)


class YahooMarketDataProvider(MarketDataProvider):
    """Consulta el último precio de un ticker en Yahoo Finance.

    Usa `fast_info` (rápido, poco intensivo) como vía principal y cae a `history()`
    si `fast_info` no trae datos utilizables (ticker poco líquido, fallo puntual de la API...).
    """

    def get_price(self, ticker: str) -> PriceQuote:
        price, currency = self._from_fast_info(ticker)

        if price is None:
            price, currency = self._from_history(ticker)

        if price is None:
            raise ValueError(f"Yahoo Finance no devolvió precio para '{ticker}'")

        return {"price": float(price), "currency": currency or "USD"}

    def _from_fast_info(self, ticker: str) -> tuple[float | None, str | None]:
        try:
            fast_info = yf.Ticker(ticker).fast_info
            price = fast_info["lastPrice"]
            currency = fast_info["currency"]
            return (float(price) if price is not None else None), currency
        except Exception as exc:
            logger.warning("Yahoo Finance: fast_info falló para '%s': %s", ticker, exc)
            return None, None

    def _from_history(self, ticker: str) -> tuple[float | None, str | None]:
        try:
            yf_ticker = yf.Ticker(ticker)
            history = yf_ticker.history(period="1d")
            if history.empty:
                return None, None
            price = float(history["Close"].iloc[-1])
        except Exception as exc:
            logger.warning("Yahoo Finance: history() falló para '%s': %s", ticker, exc)
            return None, None

        currency: str | None = None
        try:
            currency = yf_ticker.info.get("currency")
        except Exception as exc:
            logger.warning("Yahoo Finance: no se pudo leer 'currency' de info() para '%s': %s", ticker, exc)

        return price, currency
