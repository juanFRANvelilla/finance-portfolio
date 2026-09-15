from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.asset_type import AssetType
from app.schemas.asset_sale import (
    AssetSaleContextResponse,
    AssetSaleCreate,
    AssetSalePreview,
    AssetSaleRead,
)
from app.services import asset_sales as asset_sales_service

router = APIRouter(prefix="/api/investment", tags=["asset-sales"])


def _sale_to_read(sale, currency: str) -> AssetSaleRead:
    return AssetSaleRead(
        id=sale.id,
        asset_type_id=sale.asset_type_id,
        units=float(sale.units),
        sale_year=sale.sale_year,
        sale_month=sale.sale_month,
        avg_buy_price=float(sale.avg_buy_price),
        sale_price=float(sale.sale_price),
        profit=float(sale.profit),
        profit_percentage=float(sale.profit_percentage),
        currency=currency,
    )


@router.get(
    "/{year}/{month}/asset-types/{asset_type_id}/sale-context",
    response_model=AssetSaleContextResponse,
)
def get_asset_sale_context(
    year: int, month: int, asset_type_id: UUID, db: Session = Depends(get_db)
) -> AssetSaleContextResponse:
    data = asset_sales_service.get_sale_context(db, asset_type_id, year, month)
    return AssetSaleContextResponse(**data)


@router.post(
    "/{year}/{month}/asset-types/{asset_type_id}/sale-preview",
    response_model=AssetSalePreview,
)
def preview_asset_sale(
    year: int,
    month: int,
    asset_type_id: UUID,
    payload: AssetSaleCreate,
    db: Session = Depends(get_db),
) -> AssetSalePreview:
    data = asset_sales_service.preview_sale(
        db,
        asset_type_id,
        year,
        month,
        units=payload.units,
        sale_price=payload.sale_price,
    )
    return AssetSalePreview(**data)


@router.post(
    "/{year}/{month}/asset-types/{asset_type_id}/sales",
    response_model=AssetSaleRead,
    status_code=201,
)
def register_asset_sale(
    year: int,
    month: int,
    asset_type_id: UUID,
    payload: AssetSaleCreate,
    db: Session = Depends(get_db),
) -> AssetSaleRead:
    asset = db.get(AssetType, asset_type_id)
    sale = asset_sales_service.create_asset_sale(
        db,
        asset_type_id,
        year,
        month,
        units=payload.units,
        sale_price=payload.sale_price,
    )
    currency = asset.currency if asset else "EUR"
    return _sale_to_read(sale, currency)
