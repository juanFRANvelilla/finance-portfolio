from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
        sale_date=sale.sale_date,
        avg_buy_price=float(sale.avg_buy_price),
        sale_price=float(sale.sale_price),
        fee=float(sale.fee),
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
        fee=payload.fee,
        cost_basis=payload.cost_basis,
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
    if payload.sale_date is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sale_date es obligatorio")

    asset = db.get(AssetType, asset_type_id)
    sale = asset_sales_service.create_asset_sale(
        db,
        asset_type_id,
        year,
        month,
        units=payload.units,
        sale_price=payload.sale_price,
        fee=payload.fee,
        cost_basis=payload.cost_basis,
        sale_date=payload.sale_date,
    )
    currency = asset.currency if asset else "EUR"
    return _sale_to_read(sale, currency)


v1_router = APIRouter(prefix="/api/v1", tags=["asset-sales"])


@v1_router.post("/assets/{asset_type_id}/sell", response_model=AssetSaleRead, status_code=201)
def register_asset_sale_v1(
    asset_type_id: UUID,
    payload: AssetSaleCreate,
    year: int = Query(..., ge=2000),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> AssetSaleRead:
    return register_asset_sale(year, month, asset_type_id, payload, db)
