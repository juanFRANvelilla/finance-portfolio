from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.ledger import (
    EntityLedgerGroup,
    LedgerProfitRequest,
    LedgerProfitResponse,
    LedgerUnitPriceResponse,
)
from app.services.fx_converter import get_usd_to_eur_rate
from app.services.ledger import build_investment_ledger
from app.services.ledger_profit import calculate_ledger_profit, default_unit_price_eur_to_currency

router = APIRouter(prefix="/api/investment", tags=["ledger"])


@router.get("/ledger", response_model=list[EntityLedgerGroup])
def get_investment_ledger(db: Session = Depends(get_db)) -> list[EntityLedgerGroup]:
    """Histórico completo de fiat_deposits + asset_transactions, agrupado por entidad.

    Solo incluye entidades con al menos un depósito o un activo con transacciones;
    dentro de cada entidad, solo activos que tengan >= 1 fila en asset_transactions.
    """
    return build_investment_ledger(db)


@router.get("/{year}/{month}/ledger/unit-price", response_model=LedgerUnitPriceResponse)
def get_default_unit_price(
    year: int, month: int, price_eur: float, currency: str
) -> LedgerUnitPriceResponse:
    """Convierte un precio en EUR (p. ej. último precio de compra) a la divisa indicada."""
    if currency not in ("EUR", "USD"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Divisa no soportada")
    return LedgerUnitPriceResponse(
        price=default_unit_price_eur_to_currency(price_eur, currency, year, month),
        currency=currency,
        fx_usd_to_eur=get_usd_to_eur_rate(year, month),
    )


@router.post("/ledger/profit", response_model=LedgerProfitResponse)
def calculate_asset_profit(payload: LedgerProfitRequest) -> LedgerProfitResponse:
    """Beneficio en EUR = valor de mercado (precio en EUR/USD) − coste acumulado en EUR."""
    profit, profit_pct, fx_rate = calculate_ledger_profit(
        asset_acumulado=payload.asset_acumulado,
        euros_totales=payload.euros_totales,
        price=payload.price,
        currency=payload.currency,
        year=payload.year,
        month=payload.month,
    )
    return LedgerProfitResponse(
        profit=profit,
        profit_percentage=profit_pct,
        fx_usd_to_eur=fx_rate,
    )
