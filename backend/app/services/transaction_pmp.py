"""Precio medio ponderado (PMP) y coste imputado en ventas sobre asset_transactions."""

from __future__ import annotations

from decimal import Decimal

PMP_PRICE_QUANT = Decimal("0.0001")
INVESTED_QUANT = Decimal("0.00000001")


def avg_buy_price_from_position(
    units_before: Decimal, invested_before: Decimal
) -> Decimal:
    if units_before <= 0:
        return Decimal("0")
    return (invested_before / units_before).quantize(PMP_PRICE_QUANT)


def sell_cost_basis(
    *,
    units_before: Decimal,
    invested_before: Decimal,
    sold_units: Decimal,
) -> tuple[Decimal, Decimal]:
    """Devuelve (PMP unitario, coste total imputado a la venta, positivo)."""
    avg = avg_buy_price_from_position(units_before, invested_before)
    cost = (avg * sold_units).quantize(INVESTED_QUANT)
    return avg, cost


def negative_invested_for_sell(
    *,
    units_before: Decimal,
    invested_before: Decimal,
    sold_units: Decimal,
) -> tuple[Decimal, Decimal]:
    """PMP y `invested_amount` negativo para persistir en la fila de venta."""
    avg, cost = sell_cost_basis(
        units_before=units_before,
        invested_before=invested_before,
        sold_units=sold_units,
    )
    return avg, -cost
