from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.ledger import EntityLedgerGroup
from app.services.ledger import build_investment_ledger

router = APIRouter(prefix="/api/investment", tags=["ledger"])


@router.get("/ledger", response_model=list[EntityLedgerGroup])
def get_investment_ledger(db: Session = Depends(get_db)) -> list[EntityLedgerGroup]:
    """Histórico completo de fiat_deposits + asset_transactions, agrupado por entidad.

    Solo incluye entidades con al menos un depósito o un activo con transacciones;
    dentro de cada entidad, solo activos que tengan >= 1 fila en asset_transactions.
    """
    return build_investment_ledger(db)
