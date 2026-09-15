"""Conversión de importes a EUR en memoria (no se persiste en BD).

Usa la API pública Frankfurter (datos del BCE): https://www.frankfurter.app/
"""

from __future__ import annotations

import calendar
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal

import certifi

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.app"
FALLBACK_USD_EUR = 0.92
"""Timeout total de la petición HTTP (segundos)."""
FRANKFURTER_TIMEOUT_SEC = 2.0
"""Tras un fallo, no se vuelve a llamar a la API para esa fecha hasta pasado este tiempo."""
FRANKFURTER_FAIL_COOLDOWN_SEC = 300.0

_rate_cache: dict[str, float] = {}
_fail_cooldown_until: dict[str, float] = {}
_fail_logged: set[str] = set()


def _reference_date(year: int, month: int) -> date:
    """Fecha de referencia para el tipo de cambio del mes consultado."""
    today = date.today()
    if year == today.year and month == today.month:
        return today
    last_day = calendar.monthrange(year, month)[1]
    ref = date(year, month, last_day)
    return min(ref, today)


def _fallback_usd_eur_rate(cache_key: str) -> float:
    if _rate_cache:
        return next(reversed(_rate_cache.values()))
    logger.debug("USD→EUR fallback fijo %s para %s", FALLBACK_USD_EUR, cache_key)
    return FALLBACK_USD_EUR


def _mark_frankfurter_failure(cache_key: str, exc: Exception) -> float:
    _fail_cooldown_until[cache_key] = time.monotonic() + FRANKFURTER_FAIL_COOLDOWN_SEC
    if cache_key not in _fail_logged:
        _fail_logged.add(cache_key)
        logger.warning(
            "Frankfurter API no disponible para %s: %s (usando fallback; sin reintentos durante %ss)",
            cache_key,
            exc,
            int(FRANKFURTER_FAIL_COOLDOWN_SEC),
        )
    return _fallback_usd_eur_rate(cache_key)


def get_usd_to_eur_rate(year: int, month: int) -> float:
    """Obtiene el tipo USD→EUR para el mes indicado (cacheado en memoria)."""
    ref = _reference_date(year, month)
    cache_key = ref.isoformat()
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    now = time.monotonic()
    cooldown_until = _fail_cooldown_until.get(cache_key)
    if cooldown_until is not None and now < cooldown_until:
        return _fallback_usd_eur_rate(cache_key)

    url = f"{FRANKFURTER_BASE}/{cache_key}?from=USD&to=EUR"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "finance-portfolio/1.0"})
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(
            request, timeout=FRANKFURTER_TIMEOUT_SEC, context=ssl_context
        ) as response:
            data = json.loads(response.read().decode())
        rate = float(data["rates"]["EUR"])
        _rate_cache[cache_key] = rate
        _fail_cooldown_until.pop(cache_key, None)
        _fail_logged.discard(cache_key)
        logger.info("Tipo USD→EUR para %s: %s", cache_key, rate)
        return rate
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
        return _mark_frankfurter_failure(cache_key, exc)


def amount_to_eur(amount: float, currency: str, year: int, month: int) -> float:
    """Devuelve el equivalente en EUR de un importe en su divisa nativa."""
    value = Decimal(str(amount))
    if currency == "EUR":
        return float(value.quantize(Decimal("0.01")))
    if currency == "USD":
        rate = Decimal(str(get_usd_to_eur_rate(year, month)))
        return float((value * rate).quantize(Decimal("0.01")))
    return float(value.quantize(Decimal("0.01")))


def eur_to_native(amount_eur: float, currency: str, year: int, month: int) -> float:
    """Convierte un importe en EUR a la divisa nativa del activo."""
    value = Decimal(str(amount_eur))
    if currency == "EUR":
        return float(value.quantize(Decimal("0.01")))
    if currency == "USD":
        rate = Decimal(str(get_usd_to_eur_rate(year, month)))
        if rate == 0:
            return float(value.quantize(Decimal("0.01")))
        return float((value / rate).quantize(Decimal("0.01")))
    return float(value.quantize(Decimal("0.01")))
