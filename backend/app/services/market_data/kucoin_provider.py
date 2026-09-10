"""Proveedor de precios de mercado en vivo vía KuCoin (ccxt)."""

from __future__ import annotations

import logging

import ccxt

from app.services.market_data.base import MarketDataProvider, PriceQuote

logger = logging.getLogger(__name__)


class KucoinMarketDataProvider(MarketDataProvider):
    """Consulta el último precio (`last`) de un par en KuCoin.

    El `ticker` de `asset_types` se espera en formato 'BASE-QUOTE' (p.ej. 'BTC-EUR',
    'SOL-USDT') y se traduce al formato de símbolo que usa ccxt ('BTC/EUR').
    """

    def __init__(self) -> None:
        self._exchange: ccxt.kucoin | None = None

    def _get_exchange(self) -> ccxt.kucoin:
        # Los datos de ticker son públicos: no requieren API key/secret/passphrase.
        if self._exchange is None:
            self._exchange = ccxt.kucoin({"enableRateLimit": True})
        return self._exchange

    @staticmethod
    def _map_symbol(ticker: str) -> tuple[str, str]:
        cleaned = ticker.strip().upper()
        if "-" not in cleaned:
            raise ValueError(f"Ticker KuCoin inválido, se espera formato 'BASE-QUOTE': '{ticker}'")
        base, quote = cleaned.split("-", 1)
        if not base or not quote:
            raise ValueError(f"Ticker KuCoin inválido, se espera formato 'BASE-QUOTE': '{ticker}'")
        return f"{base}/{quote}", quote

    def get_price(self, ticker: str) -> PriceQuote:
        symbol, quote_currency = self._map_symbol(ticker)
        exchange = self._get_exchange()

        try:
            ticker_data = exchange.fetch_ticker(symbol)
        except Exception as exc:
            logger.warning("KuCoin: fallo al consultar ticker '%s' (%s): %s", symbol, ticker, exc)
            raise

        last_price = ticker_data.get("last")
        if last_price is None:
            raise ValueError(f"KuCoin no devolvió precio 'last' para '{symbol}'")

        # USDT se expone como USD para homogeneizar con el resto de activos en dólares.
        display_currency = "USD" if quote_currency == "USDT" else quote_currency
        return {"price": float(last_price), "currency": display_currency}
