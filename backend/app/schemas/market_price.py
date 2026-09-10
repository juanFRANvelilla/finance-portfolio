from pydantic import BaseModel


class MarketPriceResponse(BaseModel):
    asset_type_id: str
    ticker: str
    price: float
    currency: str
    updated_at: str
