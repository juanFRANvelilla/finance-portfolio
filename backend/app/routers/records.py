from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.entity import Entity, EntityType
from app.models.monthly_entity_position import MonthlyEntityPosition
from app.schemas.entity import EntityRead
from app.schemas.monthly_record import (
    EntityBalanceInput,
    EntityBalanceRead,
    EntityBalancesPatch,
    HybridAccountRead,
    HybridBalanceImport,
    HybridBalancesPatch,
    ImportPayload,
    MonthlyRecordDto,
    MonthlyRecordResponse,
    MonthlyRecordUpsert,
    TimelinePoint,
    TimelineResponse,
)
from app.services.record_calculator import (
    compute_totals_from_import,
    compute_totals_from_positions,
    compute_totals_from_simple_balances,
)
from app.services.entity_cash_flows import cash_flow_totals_by_entity


router = APIRouter(prefix="/api/records", tags=["records"])

AMOUNT_TOLERANCE = Decimal("0.02")


def _previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _get_month_positions(db: Session, year: int, month: int) -> list[MonthlyEntityPosition]:
    stmt = (
        select(MonthlyEntityPosition)
        .options(selectinload(MonthlyEntityPosition.entity))
        .where(MonthlyEntityPosition.year == year, MonthlyEntityPosition.month == month)
        .order_by(MonthlyEntityPosition.entity_id)
    )
    return list(db.scalars(stmt).all())


def _month_has_positions(db: Session, year: int, month: int) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(MonthlyEntityPosition)
        .where(MonthlyEntityPosition.year == year, MonthlyEntityPosition.month == month)
    )
    return bool(count and count > 0)


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El mes debe estar entre 1 y 12")


def _load_entities(db: Session, entity_ids: set[str]) -> dict[str, Entity]:
    if not entity_ids:
        return {}
    stmt = select(Entity).where(Entity.id.in_(entity_ids))
    return {entity.id: entity for entity in db.scalars(stmt).all()}


def _totals_for_month(db: Session, year: int, month: int) -> dict[str, float] | None:
    positions = _get_month_positions(db, year, month)
    if not positions:
        return None
    return compute_totals_from_positions(positions)


def _split_positions_for_dto(
    positions: list[MonthlyEntityPosition],
) -> tuple[list[EntityBalanceRead], list[HybridAccountRead]]:
    balances: list[EntityBalanceRead] = []
    hybrids: list[HybridAccountRead] = []
    for position in positions:
        entity = position.entity
        entity_type = entity.entity_type if entity else None
        entity_read = EntityRead.model_validate(entity) if entity is not None else None
        if entity_type == EntityType.HYBRID:
            hybrids.append(
                HybridAccountRead(
                    entity_id=position.entity_id,
                    liquid_amount=float(position.liquid_amount),
                    cumulative_invested=float(position.cumulative_invested),
                    entity=entity_read,
                )
            )
        else:
            balances.append(
                EntityBalanceRead(
                    entity_id=position.entity_id,
                    balance_amount=float(position.liquid_amount),
                    entity=entity_read,
                )
            )
    return balances, hybrids


def _to_dto(
    *,
    year: int,
    month: int,
    positions: list[MonthlyEntityPosition],
    previous_net_worth: float | None,
    previous_total_invested: float | None,
) -> MonthlyRecordDto:
    totals = compute_totals_from_positions(positions)
    total_liquid = totals["total_liquid"]
    total_invested = totals["total_invested"]
    total_net_worth = totals["total_net_worth"]
    invested_percentage = totals["invested_percentage"]
    monthly_diff = total_net_worth - previous_net_worth if previous_net_worth is not None else None
    invested_diff = (
        total_invested - previous_total_invested if previous_total_invested is not None else None
    )

    balances, hybrid_accounts = _split_positions_for_dto(positions)
    representative = min(positions, key=lambda p: p.created_at)

    return MonthlyRecordDto(
        id=representative.id,
        year=year,
        month=month,
        created_at=representative.created_at,
        balances=balances,
        hybrid_accounts=hybrid_accounts,
        total_liquid=total_liquid,
        total_invested=total_invested,
        total_net_worth=total_net_worth,
        invested_percentage=round(invested_percentage, 2),
        monthly_diff=monthly_diff,
        invested_diff=invested_diff,
    )


def _build_response(
    *,
    year: int,
    month: int,
    db: Session,
) -> MonthlyRecordResponse:
    prev_year, prev_month = _previous_year_month(year, month)
    previous_totals = _totals_for_month(db, prev_year, prev_month)
    previous_net_worth = previous_totals["total_net_worth"] if previous_totals else None
    previous_total_invested = previous_totals["total_invested"] if previous_totals else None
    entity_balance_previews = cash_flow_totals_by_entity(db)

    positions = _get_month_positions(db, year, month)
    if not positions:
        return MonthlyRecordResponse(
            exists=False,
            year=year,
            month=month,
            record=None,
            previous_net_worth=previous_net_worth,
            previous_total_invested=previous_total_invested,
            entity_balance_previews=entity_balance_previews,
        )

    return MonthlyRecordResponse(
        exists=True,
        year=year,
        month=month,
        record=_to_dto(
            year=year,
            month=month,
            positions=positions,
            previous_net_worth=previous_net_worth,
            previous_total_invested=previous_total_invested,
        ),
        previous_net_worth=previous_net_worth,
        previous_total_invested=previous_total_invested,
        entity_balance_previews=entity_balance_previews,
    )


def _validate_balance_entity_types(
    simple_balances: list,
    hybrid_balances: list,
    entities_by_id: dict[str, Entity],
) -> None:
    all_ids = [b.entity_id for b in simple_balances] + [h.entity_id for h in hybrid_balances]
    if len(all_ids) != len(set(all_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hay entity_id duplicados en los balances simples o híbridos",
        )

    unknown_ids = set(all_ids) - set(entities_by_id.keys())
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Entidades desconocidas: {sorted(unknown_ids)}",
        )

    for balance in simple_balances:
        entity_type = entities_by_id[balance.entity_id].entity_type
        if entity_type != EntityType.LIQUID:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La entidad '{balance.entity_id}' debe ser LIQUID",
            )

    for hybrid in hybrid_balances:
        entity_type = entities_by_id[hybrid.entity_id].entity_type
        if entity_type != EntityType.HYBRID:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La entidad '{hybrid.entity_id}' debe ser HYBRID",
            )


def _assert_totals_match(computed: dict[str, float], payload: ImportPayload) -> None:
    checks = {
        "total_liquid": (computed["total_liquid"], payload.expected_totals.total_liquid),
        "total_invested": (computed["total_invested"], payload.expected_totals.total_invested),
        "total_net_worth": (computed["total_net_worth"], payload.expected_totals.total_net_worth),
    }

    mismatches: list[str] = []
    for field, (calc, exp) in checks.items():
        if abs(Decimal(str(calc)) - Decimal(str(exp))) > AMOUNT_TOLERANCE:
            mismatches.append(f"{field}: calculado={calc:.2f}, esperado={exp:.2f}")

    if mismatches:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Los totales calculados no coinciden con expected_totals", "mismatches": mismatches},
        )


def _validate_import_payload(payload: ImportPayload, entities_by_id: dict[str, Entity]) -> None:
    _validate_balance_entity_types(payload.simple_balances, payload.hybrid_balances, entities_by_id)

    if not payload.simple_balances and not payload.hybrid_balances:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El payload debe incluir al menos un balance simple o híbrido",
        )


def _resolve_hybrid_invested(hybrid_balances: list) -> list[tuple[str, float, float]]:
    """Devuelve (entity_id, liquid_amount, cumulative_invested) listo para persistir."""
    resolved: list[tuple[str, float, float]] = []
    for hybrid in hybrid_balances:
        liquid = float(hybrid.liquid_amount)
        if hybrid.invested_amount is not None:
            invested = float(hybrid.invested_amount)
        else:
            invested = 0.0
        resolved.append((hybrid.entity_id, liquid, invested))
    return resolved


def _get_position(db: Session, year: int, month: int, entity_id: str) -> MonthlyEntityPosition | None:
    return db.scalars(
        select(MonthlyEntityPosition).where(
            MonthlyEntityPosition.year == year,
            MonthlyEntityPosition.month == month,
            MonthlyEntityPosition.entity_id == entity_id,
        )
    ).first()


def _upsert_liquid_positions(
    db: Session,
    *,
    year: int,
    month: int,
    simple_balances: list,
) -> None:
    for balance in simple_balances:
        amount = balance.amount if hasattr(balance, "amount") else balance.balance_amount
        existing = _get_position(db, year, month, balance.entity_id)
        if existing is not None:
            existing.liquid_amount = amount
            existing.cumulative_invested = 0
        else:
            db.add(
                MonthlyEntityPosition(
                    year=year,
                    month=month,
                    entity_id=balance.entity_id,
                    liquid_amount=amount,
                    cumulative_invested=0,
                )
            )


def _upsert_hybrid_positions(
    db: Session,
    *,
    year: int,
    month: int,
    resolved_hybrids: list[tuple[str, float, float]],
) -> None:
    for entity_id, liquid, invested in resolved_hybrids:
        existing = _get_position(db, year, month, entity_id)
        if existing is not None:
            existing.liquid_amount = liquid
            existing.cumulative_invested = invested
        else:
            db.add(
                MonthlyEntityPosition(
                    year=year,
                    month=month,
                    entity_id=entity_id,
                    liquid_amount=liquid,
                    cumulative_invested=invested,
                )
            )


def _patch_simple_balances(
    db: Session,
    *,
    year: int,
    month: int,
    simple_balances: list,
) -> None:
    entity_ids = {b.entity_id for b in simple_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_balance_entity_types(simple_balances, [], entities_by_id)
    _upsert_liquid_positions(db, year=year, month=month, simple_balances=simple_balances)
    db.commit()


def _patch_hybrid_balances(
    db: Session,
    *,
    year: int,
    month: int,
    hybrid_balances: list,
) -> None:
    entity_ids = {h.entity_id for h in hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_balance_entity_types([], hybrid_balances, entities_by_id)
    resolved_hybrids = _resolve_hybrid_invested(hybrid_balances)
    _upsert_hybrid_positions(db, year=year, month=month, resolved_hybrids=resolved_hybrids)
    db.commit()


def _upsert_record_balances(
    db: Session,
    *,
    year: int,
    month: int,
    simple_balances: list,
    hybrid_balances: list,
) -> None:
    _upsert_liquid_positions(db, year=year, month=month, simple_balances=simple_balances)

    resolved_hybrids = _resolve_hybrid_invested(hybrid_balances)
    _upsert_hybrid_positions(db, year=year, month=month, resolved_hybrids=resolved_hybrids)
    db.commit()


@router.get("/timeline", response_model=TimelineResponse)
def get_records_timeline(db: Session = Depends(get_db)) -> TimelineResponse:
    """Serie temporal mes a mes con patrimonio e invertido calculados desde monthly_entity_positions."""
    stmt = (
        select(
            MonthlyEntityPosition.year,
            MonthlyEntityPosition.month,
            func.sum(MonthlyEntityPosition.liquid_amount + MonthlyEntityPosition.cumulative_invested).label(
                "total_net_worth"
            ),
            func.sum(MonthlyEntityPosition.cumulative_invested).label("total_invested"),
        )
        .group_by(MonthlyEntityPosition.year, MonthlyEntityPosition.month)
        .order_by(MonthlyEntityPosition.year, MonthlyEntityPosition.month)
    )
    rows = db.execute(stmt).all()

    points: list[TimelinePoint] = []
    previous_net_worth: float | None = None
    previous_invested: float | None = None

    for row in rows:
        net_worth = float(row.total_net_worth or 0)
        invested = float(row.total_invested or 0)
        points.append(
            TimelinePoint(
                year=row.year,
                month=row.month,
                total_net_worth=net_worth,
                total_invested=invested,
                net_worth_diff=net_worth - previous_net_worth if previous_net_worth is not None else None,
                invested_diff=invested - previous_invested if previous_invested is not None else None,
            )
        )
        previous_net_worth = net_worth
        previous_invested = invested

    return TimelineResponse(points=points)


@router.get("/{year}/{month}", response_model=MonthlyRecordResponse)
def get_monthly_record(year: int, month: int, db: Session = Depends(get_db)) -> MonthlyRecordResponse:
    _validate_month(month)
    return _build_response(year=year, month=month, db=db)


@router.patch("/{year}/{month}/balances", response_model=MonthlyRecordResponse)
def patch_entity_balances(
    year: int,
    month: int,
    payload: EntityBalancesPatch,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Actualiza balances LIQUID sin tocar posiciones híbridas del mes."""
    _validate_month(month)
    _patch_simple_balances(
        db,
        year=year,
        month=month,
        simple_balances=payload.balances,
    )
    return _build_response(year=year, month=month, db=db)


@router.patch("/{year}/{month}/hybrids", response_model=MonthlyRecordResponse)
def patch_hybrid_balances(
    year: int,
    month: int,
    payload: HybridBalancesPatch,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Actualiza líquido/invertido de híbridas sin tocar entidades LIQUID del mes."""
    _validate_month(month)
    _patch_hybrid_balances(
        db,
        year=year,
        month=month,
        hybrid_balances=payload.hybrid_balances,
    )
    return _build_response(year=year, month=month, db=db)


@router.post("/{year}/{month}", response_model=MonthlyRecordResponse)
def upsert_monthly_record(
    year: int,
    month: int,
    payload: MonthlyRecordUpsert,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Crea o actualiza posiciones por entidad (LIQUID + HYBRID) de un mes."""
    _validate_month(month)

    entity_ids = {b.entity_id for b in payload.balances} | {h.entity_id for h in payload.hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_balance_entity_types(payload.balances, payload.hybrid_balances, entities_by_id)

    positions = _get_month_positions(db, year, month)
    existing_hybrids = [
        (p.entity_id, float(p.liquid_amount), float(p.cumulative_invested))
        for p in positions
        if p.entity and p.entity.entity_type == EntityType.HYBRID
    ]
    resolved_hybrids = _resolve_hybrid_invested(payload.hybrid_balances)
    resolved_ids = {eid for eid, _, _ in resolved_hybrids}
    merged_hybrids = [(eid, liq, inv) for eid, liq, inv in existing_hybrids if eid not in resolved_ids]
    merged_hybrids.extend(resolved_hybrids)

    compute_totals_from_simple_balances(
        payload.balances,
        entities_by_id,
        resolved_hybrids=merged_hybrids,
    )

    _upsert_record_balances(
        db,
        year=year,
        month=month,
        simple_balances=payload.balances,
        hybrid_balances=payload.hybrid_balances,
    )
    return _build_response(year=year, month=month, db=db)


@router.delete("/{year}/{month}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monthly_record(year: int, month: int, db: Session = Depends(get_db)) -> None:
    """Elimina todas las posiciones de entidad de un mes."""
    _validate_month(month)
    if not _month_has_positions(db, year, month):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe registro para ese mes")

    db.execute(
        delete(MonthlyEntityPosition).where(
            MonthlyEntityPosition.year == year,
            MonthlyEntityPosition.month == month,
        )
    )
    db.commit()


@router.post("/{year}/{month}/import", response_model=MonthlyRecordResponse)
def import_monthly_record(
    year: int,
    month: int,
    payload: ImportPayload,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Importa un mes completo, valida expected_totals y persiste posiciones por entidad."""
    _validate_month(month)

    entity_ids = {b.entity_id for b in payload.simple_balances} | {h.entity_id for h in payload.hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_import_payload(payload, entities_by_id)

    resolved_hybrids = _resolve_hybrid_invested(payload.hybrid_balances)
    simple_inputs = [
        EntityBalanceInput(entity_id=b.entity_id, balance_amount=b.amount)
        for b in payload.simple_balances
    ]
    totals = compute_totals_from_simple_balances(
        simple_inputs,
        entities_by_id,
        resolved_hybrids=resolved_hybrids,
    )
    _assert_totals_match(totals, payload)

    _upsert_record_balances(
        db,
        year=year,
        month=month,
        simple_balances=payload.simple_balances,
        hybrid_balances=payload.hybrid_balances,
    )
    return _build_response(year=year, month=month, db=db)
