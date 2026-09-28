from decimal import Decimal

from app.services.fx_converter import amount_to_eur, eur_to_native, get_usd_to_eur_rate


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _round4(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001")))


def calculate_ledger_profit(
    *,
    asset_acumulado: float,
    euros_totales: float,
    price: float,
    currency: str,
    year: int,
    month: int,
) -> tuple[float, float, float]:
    """Calcula beneficio y % en EUR.

    Precio y coste (`euros_totales`) llegan en `currency`, la divisa del activo.
    Si ya es EUR, no hay conversión. Si es USD, mercado y coste usan el mismo tipo
    solo para devolver el beneficio en euros.
    """
    units = Decimal(str(asset_acumulado))
    unit_price = Decimal(str(price))
    cost = Decimal(str(euros_totales))

    market_native = units * unit_price
    if currency == "EUR":
        market_eur = market_native
        cost_eur = cost
    else:
        market_eur = Decimal(str(amount_to_eur(float(market_native), currency, year, month)))
        cost_eur = Decimal(str(amount_to_eur(float(cost), currency, year, month)))

    profit_eur = market_eur - cost_eur
    profit_pct = (profit_eur / cost_eur * Decimal("100")) if cost_eur > 0 else Decimal("0")

    fx_rate = get_usd_to_eur_rate(year, month)
    return _round2(profit_eur), _round4(profit_pct), fx_rate


def default_unit_price_eur_to_currency(price_eur: float, currency: str, year: int, month: int) -> float:
    """Convierte el último precio de compra (EUR) a la divisa nativa del activo."""
    return eur_to_native(price_eur, currency, year, month)
