import logging
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.monthly_category_expense import MonthlyCategoryExpense
from app.schemas.expense import MonthlyExpensesResponse
from app.services.expenses_service import get_monthly_expenses, import_expenses_for_month

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


@router.get("/{year}/{month}", response_model=MonthlyExpensesResponse)
def get_expenses_by_month(
    year: int,
    month: int,
    db: Session = Depends(get_db),
) -> MonthlyExpensesResponse:
    """Devuelve el snapshot de gastos del mes consultado."""
    if not (1 <= month <= 12):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El mes debe estar entre 1 y 12")
    return get_monthly_expenses(db, year, month)


@router.post("/{year}/{month}/import", response_model=MonthlyExpensesResponse)
async def import_expenses_excel(
    year: int,
    month: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> MonthlyExpensesResponse:
    """Importa uno o varios ficheros Excel (.xls / .xlsx) de Santander (cuenta corriente y/o tarjeta de crédito)."""
    if not (1 <= month <= 12):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El mes debe estar entre 1 y 12")

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Debes proporcionar al menos un fichero Excel")

    files_data: list[tuple[str, bytes]] = []
    for file in files:
        content = await file.read()
        files_data.append((file.filename or "unknown.xls", content))

    try:
        response = import_expenses_for_month(db, files_data, year, month)
        return response
    except Exception as e:
        logger.exception("Error importando ficheros de gastos para %s/%s: %s", year, month, e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error procesando los ficheros: {str(e)}")


@router.delete("/{year}/{month}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expenses_by_month(
    year: int,
    month: int,
    db: Session = Depends(get_db),
) -> None:
    """Elimina los gastos registrados de un mes concreto."""
    db.execute(
        delete(MonthlyCategoryExpense).where(
            MonthlyCategoryExpense.year == year,
            MonthlyCategoryExpense.month == month,
        )
    )
    db.commit()
