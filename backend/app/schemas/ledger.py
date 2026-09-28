from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ALLOWED_CURRENCIES = ("EUR", "USD")


class FiatDepositRow(BaseModel):
    fecha: date | None = None
    cantidad: float
    total_acumulado: float
    """Suma acumulada de depósitos fiat de la entidad hasta esta fila (inclusive)."""


class AssetTransactionLedgerRow(BaseModel):
    fecha: date | None = None
    precio_promedio: float
    """Coste medio acumulado (importe total / títulos) en la divisa del activo."""
    precio_compra: float
    """Precio de ejecución de esta operación (execution_price, divisa del activo)."""
    euros_metidos: float
    """Importe de esta operación. Es el número guardado; la divisa es la del activo."""
    euros_totales: float
    """Importe acumulado en este activo. Misma divisa que el activo, sin convertir."""
    asset_comprado: float
    """Unidades del activo compradas en esta operación."""
    asset_acumulado: float
    """Unidades acumuladas del activo hasta esta fila."""


class AssetLedgerGroup(BaseModel):
    asset_type_id: str
    exchange_ticker: str
    currency: str
    """Divisa nativa del activo (EUR o USD según asset_types)."""
    total_asset_acumulado: float = 0
    total_euros_metidos: float = 0
    """Coste acumulado (suma de asset_transactions) en la divisa del activo."""
    last_precio_compra: float = 0
    """Precio de la última operación, en la divisa del activo."""
    transactions: list[AssetTransactionLedgerRow] = Field(default_factory=list)


class LedgerProfitRequest(BaseModel):
    asset_acumulado: float = Field(gt=0)
    euros_totales: float = Field(ge=0)
    price: float = Field(gt=0)
    """Precio unitario indicado por el usuario."""
    currency: Literal["EUR", "USD"]
    """Divisa en la que se interpreta el precio unitario (el beneficio siempre se devuelve en EUR)."""
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if value not in ALLOWED_CURRENCIES:
            raise ValueError(f"La divisa debe ser una de {ALLOWED_CURRENCIES}")
        return value


class LedgerProfitResponse(BaseModel):
    profit: float
    """Beneficio/pérdida en EUR."""
    profit_percentage: float
    fx_usd_to_eur: float
    """Tipo USD→EUR usado cuando el precio unitario está en USD."""


class LedgerUnitPriceResponse(BaseModel):
    price: float
    currency: str
    fx_usd_to_eur: float


class EntityLedgerGroup(BaseModel):
    entity_name: str
    fiat_deposits: list[FiatDepositRow] = Field(default_factory=list)
    assets: list[AssetLedgerGroup] = Field(default_factory=list)
