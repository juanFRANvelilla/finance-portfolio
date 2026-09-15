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
    """Importe total de la posición en divisa nativa (avg × position_units)."""


class AssetSaleCreate(BaseModel):
    units: float = Field(gt=0)
    sale_price: float = Field(ge=0)


class AssetSalePreview(BaseModel):
    units: float
    sale_price: float
    avg_buy_price: float
    profit: float
    profit_percentage: float
    position_share_pct: float
    """Porcentaje de la posición disponible que se vende."""


class AssetSaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_type_id: UUID
    units: float
    sale_year: int
    sale_month: int
    avg_buy_price: float
    sale_price: float
    profit: float
    profit_percentage: float
    currency: str
