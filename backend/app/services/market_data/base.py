"""Interfaz común para proveedores de precios de mercado."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class PriceQuote(TypedDict):
    """Resultado normalizado de un proveedor de precios."""

    price: float
    currency: str


class MarketDataProvider(ABC):
    """Contrato que debe cumplir cualquier proveedor de precios de mercado."""

    @abstractmethod
    def get_price(self, ticker: str) -> PriceQuote:
        """Devuelve `{"price": float, "currency": str}` para `ticker`.

        Debe lanzar una excepción (ValueError, RuntimeError, error del SDK, etc.) si no
        puede resolver el precio; el orquestador (`MarketPriceService`) es responsable de
        capturarla para que un ticker fallido no tumbe el resto de la respuesta.
        """
        raise NotImplementedError
