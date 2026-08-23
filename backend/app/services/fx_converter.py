"""Conversión de importes a EUR en memoria (no se persiste en BD).

TODO: integrar una API de tipos de cambio (p. ej. Frankfurter) para USD→EUR real.
"""

from decimal import Decimal


def amount_to_eur(amount: float, currency: str) -> float:
    """Devuelve el equivalente en EUR de un importe en su divisa nativa."""
    value = Decimal(str(amount))
    if currency == "EUR":
        return float(value.quantize(Decimal("0.01")))
    if currency == "USD":
        # Placeholder 1:1 hasta conectar API de FX.
        return float(value.quantize(Decimal("0.01")))
    return float(value.quantize(Decimal("0.01")))
