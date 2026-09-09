from datetime import date

from pydantic import BaseModel, Field


class FiatDepositRow(BaseModel):
    fecha: date | None = None
    cantidad: float
    total_acumulado: float
    """Suma acumulada de depósitos fiat de la entidad hasta esta fila (inclusive)."""


class AssetTransactionLedgerRow(BaseModel):
    fecha: date | None = None
    precio_promedio: float
    """Coste medio acumulado (euros_totales / asset_acumulado) hasta esta fila."""
    precio_compra: float
    """Precio de ejecución de esta operación concreta (execution_price, en EUR)."""
    euros_metidos: float
    """Importe en EUR de esta operación."""
    euros_totales: float
    """Importe en EUR acumulado invertido en este activo hasta esta fila."""
    asset_comprado: float
    """Unidades del activo compradas en esta operación."""
    asset_acumulado: float
    """Unidades acumuladas del activo hasta esta fila."""


class AssetLedgerGroup(BaseModel):
    exchange_ticker: str
    transactions: list[AssetTransactionLedgerRow] = Field(default_factory=list)


class EntityLedgerGroup(BaseModel):
    entity_name: str
    fiat_deposits: list[FiatDepositRow] = Field(default_factory=list)
    assets: list[AssetLedgerGroup] = Field(default_factory=list)
