from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssetSaleContextResponse(BaseModel):
    asset_type_id: UUID
    asset_name: str
    currency: str
    year: int
    month: int
    position_units: float
    available_units: float
    avg_buy_price: float
    cost_basis_total: float
    """Importe total de la posición en divisa nativa."""
    position_cost_basis: float
    """Capital invertido total en la posición antes de esta venta (divisa nativa)."""
    has_sale_this_month: bool


class AssetSaleCreate(BaseModel):
    units: float = Field(gt=0)
    sale_price: float = Field(ge=0)
    fee: float = Field(default=0, ge=0)
    """Comisión del broker en la divisa del activo."""
    sale_date: date | None = None
    cost_basis: float | None = Field(default=None, gt=0)
    """Coste imputado a la venta (FIFO/broker). Si es null, se usa PMP × unidades."""


class AssetSalePreview(BaseModel):
    units: float
    sale_price: float
    fee: float
    avg_buy_price: float
    cost_basis: float
    net_liquidity: float
    gross_profit: float
    profit: float
    """Beneficio neto: (precio×unidades − fee) − coste imputado."""
    profit_percentage: float
    position_share_pct: float


class AssetSaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_type_id: UUID
    units: float
    sale_year: int
    sale_month: int
    sale_date: date | None = None
    avg_buy_price: float
    sale_price: float
    fee: float
    profit: float
    profit_percentage: float
    currency: str
