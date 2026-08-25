"""Conversión de importes a EUR en memoria (no se persiste en BD).

Usa la API pública Frankfurter (datos del BCE): https://www.frankfurter.app/
"""

from __future__ import annotations

import calendar
import json
import logging
import ssl
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal

import certifi

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.app"
FALLBACK_USD_EUR = 0.92

_rate_cache: dict[str, float] = {}


def _reference_date(year: int, month: int) -> date:
    """Fecha de referencia para el tipo de cambio del mes consultado."""
    today = date.today()
    if year == today.year and month == today.month:
        return today
    last_day = calendar.monthrange(year, month)[1]
    ref = date(year, month, last_day)
    return min(ref, today)


def get_usd_to_eur_rate(year: int, month: int) -> float:
    """Obtiene el tipo USD→EUR para el mes indicado (cacheado en memoria)."""
    ref = _reference_date(year, month)
    cache_key = ref.isoformat()
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    url = f"{FRANKFURTER_BASE}/{cache_key}?from=USD&to=EUR"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "finance-portfolio/1.0"})
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=8, context=ssl_context) as response:
            data = json.loads(response.read().decode())
        rate = float(data["rates"]["EUR"])
        _rate_cache[cache_key] = rate
        logger.info("Tipo USD→EUR para %s: %s", cache_key, rate)
        return rate
    except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Frankfurter API no disponible para %s: %s", cache_key, exc)
        if _rate_cache:
            return next(reversed(_rate_cache.values()))
        return FALLBACK_USD_EUR


def amount_to_eur(amount: float, currency: str, year: int, month: int) -> float:
    """Devuelve el equivalente en EUR de un importe en su divisa nativa."""
    value = Decimal(str(amount))
    if currency == "EUR":
        return float(value.quantize(Decimal("0.01")))
    if currency == "USD":
        rate = Decimal(str(get_usd_to_eur_rate(year, month)))
        return float((value * rate).quantize(Decimal("0.01")))
    return float(value.quantize(Decimal("0.01")))
