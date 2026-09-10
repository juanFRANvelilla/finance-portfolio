from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.market_price import MarketPriceResponse
from app.services.market_price_service import market_price_service

router = APIRouter(prefix="/api/v1", tags=["market-data"])


@router.get("/market-prices", response_model=list[MarketPriceResponse])
def get_market_prices(refresh: bool = False, db: Session = Depends(get_db)) -> list[MarketPriceResponse]:
    """Precios de mercado en vivo (caché ~45s) para activos con `ticker` + `price_source`."""
    items = market_price_service.get_prices(db, force_refresh=refresh)
    return [
        MarketPriceResponse(
            asset_type_id=item.asset_type_id,
            ticker=item.ticker,
            price=item.price,
            currency=item.currency,
            updated_at=item.updated_at,
        )
        for item in items
    ]
