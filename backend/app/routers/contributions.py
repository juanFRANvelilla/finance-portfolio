from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entity import Entity, EntityType
from app.models.entity_contribution import EntityContribution
from app.schemas.contribution import ContributionCreate, ContributionRead, EntityContributionsResponse
from app.services.hybrid_ledger import (
    _month_date_range,
    build_ledger_summary,
)

router = APIRouter(prefix="/api/contributions", tags=["contributions"])


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El mes debe estar entre 1 y 12")


def _get_hybrid_entity_or_404(db: Session, entity_id: str) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entidad '{entity_id}' no encontrada")
    if entity.entity_type != EntityType.HYBRID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La entidad '{entity_id}' no es híbrida",
        )
    return entity


def _assert_date_in_month(contribution_date, year: int, month: int) -> None:
    start, end = _month_date_range(year, month)
    if contribution_date < start or contribution_date > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La fecha debe estar dentro de {start.isoformat()} y {end.isoformat()}",
        )


def _get_contribution_managed_hybrid_or_404(db: Session, entity_id: str) -> Entity:
    entity = _get_hybrid_entity_or_404(db, entity_id)
    if not entity.uses_contribution_ledger:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La entidad '{entity_id}' no gestiona invertido por aportaciones",
        )
    return entity


@router.get("/{year}/{month}/{entity_id}", response_model=EntityContributionsResponse)
def list_entity_contributions(
    year: int,
    month: int,
    entity_id: str,
    liquid_amount: float = Query(default=0.0, ge=0),
    db: Session = Depends(get_db),
) -> EntityContributionsResponse:
    """Aportaciones del mes para una entidad híbrida y resumen para calcular invertido."""
    _validate_month(month)
    _get_contribution_managed_hybrid_or_404(db, entity_id)

    start, end = _month_date_range(year, month)
    contributions = list(
        db.scalars(
            select(EntityContribution)
            .where(
                EntityContribution.entity_id == entity_id,
                EntityContribution.contribution_date >= start,
                EntityContribution.contribution_date <= end,
            )
            .order_by(EntityContribution.contribution_date, EntityContribution.created_at)
        ).all()
    )

    summary = build_ledger_summary(db, entity_id, year, month, liquid_amount)

    return EntityContributionsResponse(
        entity_id=entity_id,
        year=year,
        month=month,
        contributions=[ContributionRead.model_validate(c) for c in contributions],
        previous_static_total=summary["previous_static_total"],
        contributions_total=summary["contributions_total"],
        projected_total=summary["projected_total"],
        cumulative_invested_preview=summary["cumulative_invested"],
    )


@router.post(
    "/{year}/{month}/{entity_id}",
    response_model=ContributionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_entity_contribution(
    year: int,
    month: int,
    entity_id: str,
    payload: ContributionCreate,
    db: Session = Depends(get_db),
) -> EntityContribution:
    _validate_month(month)
    _get_contribution_managed_hybrid_or_404(db, entity_id)
    _assert_date_in_month(payload.contribution_date, year, month)

    row = EntityContribution(
        entity_id=entity_id,
        contribution_date=payload.contribution_date,
        amount=payload.amount,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{contribution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity_contribution(contribution_id: UUID, db: Session = Depends(get_db)) -> None:
    row = db.get(EntityContribution, contribution_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aportación no encontrada")
    db.delete(row)
    db.commit()
