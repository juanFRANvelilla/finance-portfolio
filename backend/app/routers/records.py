from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.entity import Entity, EntityType
from app.models.monthly_entity_balance import MonthlyEntityBalance
from app.models.monthly_record import MonthlyRecord
from app.schemas.monthly_record import (
    ImportJsonPayload,
    ImportJsonResponse,
    MonthlyRecordResponse,
    MonthlyRecordUpsert,
)

router = APIRouter(prefix="/api/records", tags=["records"])


def _previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _get_record(db: Session, year: int, month: int) -> MonthlyRecord | None:
    stmt = (
        select(MonthlyRecord)
        .options(selectinload(MonthlyRecord.balances).selectinload(MonthlyEntityBalance.entity))
        .where(MonthlyRecord.year == year, MonthlyRecord.month == month)
    )
    return db.scalars(stmt).first()


@router.get("/{year}/{month}", response_model=MonthlyRecordResponse)
def get_monthly_record(year: int, month: int, db: Session = Depends(get_db)) -> MonthlyRecordResponse:
    """Devuelve los totales del mes, el detalle de balances por entidad y el net worth del mes anterior."""
    if not 1 <= month <= 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El mes debe estar entre 1 y 12")

    record = _get_record(db, year, month)

    prev_year, prev_month = _previous_year_month(year, month)
    previous_record = _get_record(db, prev_year, prev_month)
    previous_net_worth = float(previous_record.total_net_worth) if previous_record else None

    if record is None:
        return MonthlyRecordResponse(
            exists=False,
            year=year,
            month=month,
            record=None,
            previous_net_worth=previous_net_worth,
        )

    return MonthlyRecordResponse(
        exists=True,
        year=year,
        month=month,
        record=record,
        previous_net_worth=previous_net_worth,
    )


@router.post("/{year}/{month}", response_model=MonthlyRecordResponse)
def upsert_monthly_record(
    year: int,
    month: int,
    payload: MonthlyRecordUpsert,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Crea o actualiza los balances de un mes y recalcula los totales derivados."""
    if not 1 <= month <= 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El mes debe estar entre 1 y 12")

    entity_ids = [b.entity_id for b in payload.balances]
    entities_by_id: dict[str, Entity] = {}
    if entity_ids:
        stmt = select(Entity).where(Entity.id.in_(entity_ids))
        entities_by_id = {e.id: e for e in db.scalars(stmt).all()}

    unknown_ids = set(entity_ids) - set(entities_by_id.keys())
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Entidades desconocidas: {sorted(unknown_ids)}",
        )

    total_liquid = sum(
        b.balance_amount for b in payload.balances if entities_by_id[b.entity_id].entity_type == EntityType.LIQUID
    )
    total_invested = sum(
        b.balance_amount for b in payload.balances if entities_by_id[b.entity_id].entity_type == EntityType.INVESTED
    )
    total_net_worth = total_liquid + total_invested
    invested_percentage = (total_invested / total_net_worth * 100) if total_net_worth else 0.0

    prev_year, prev_month = _previous_year_month(year, month)
    previous_record = _get_record(db, prev_year, prev_month)
    monthly_diff = (
        total_net_worth - float(previous_record.total_net_worth) if previous_record else None
    )

    record = _get_record(db, year, month)
    if record is None:
        record = MonthlyRecord(year=year, month=month)
        db.add(record)
        db.flush()
    else:
        record.balances.clear()
        db.flush()

    record.total_liquid = total_liquid
    record.total_invested = total_invested
    record.total_net_worth = total_net_worth
    record.invested_percentage = invested_percentage
    record.monthly_diff = monthly_diff

    for balance_input in payload.balances:
        record.balances.append(
            MonthlyEntityBalance(
                entity_id=balance_input.entity_id,
                balance_amount=balance_input.balance_amount,
            )
        )

    db.commit()
    db.refresh(record)

    return MonthlyRecordResponse(
        exists=True,
        year=year,
        month=month,
        record=record,
        previous_net_worth=float(previous_record.total_net_worth) if previous_record else None,
    )


@router.post("/import-json", response_model=ImportJsonResponse)
def import_historical_json(payload: ImportJsonPayload, db: Session = Depends(get_db)) -> ImportJsonResponse:
    """
    Endpoint placeholder para la ingesta masiva de meses historicos via JSON.

    TODO: Implementar el parseo del JSON historico y el upsert masivo de
    MonthlyRecord + MonthlyEntityBalance reutilizando la logica de calculo
    de upsert_monthly_record (total_liquid, total_invested, total_net_worth,
    invested_percentage, monthly_diff encadenado mes a mes).
    """
    return ImportJsonResponse(
        status="not_implemented",
        imported_count=0,
        detail="Importacion masiva pendiente de implementar. Payload recibido con "
        f"{len(payload.months)} meses.",
    )
