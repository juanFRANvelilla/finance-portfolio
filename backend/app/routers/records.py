from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.entity import Entity, EntityType
from app.models.monthly_entity_balance import MonthlyEntityBalance
from app.models.monthly_hybrid_account import MonthlyHybridAccount
from app.models.monthly_record import MonthlyRecord
from app.schemas.monthly_record import (
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
    compute_totals_from_record,
    compute_totals_from_simple_balances,
)
from app.services.hybrid_ledger import compute_cumulative_invested, uses_ledger


router = APIRouter(prefix="/api/records", tags=["records"])

AMOUNT_TOLERANCE = Decimal("0.02")


def _previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _get_record(db: Session, year: int, month: int) -> MonthlyRecord | None:
    stmt = (
        select(MonthlyRecord)
        .options(
            selectinload(MonthlyRecord.balances).selectinload(MonthlyEntityBalance.entity),
            selectinload(MonthlyRecord.hybrid_accounts).selectinload(MonthlyHybridAccount.entity),
        )
        .where(MonthlyRecord.year == year, MonthlyRecord.month == month)
    )
    return db.scalars(stmt).first()


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El mes debe estar entre 1 y 12")


def _load_entities(db: Session, entity_ids: set[str]) -> dict[str, Entity]:
    if not entity_ids:
        return {}
    stmt = select(Entity).where(Entity.id.in_(entity_ids))
    return {entity.id: entity for entity in db.scalars(stmt).all()}


def _persisted_net_worth(record: MonthlyRecord | None) -> float | None:
    if record is None:
        return None
    return float(record.total_net_worth)


def _persisted_total_invested(record: MonthlyRecord | None) -> float | None:
    if record is None:
        return None
    return float(record.total_invested)


def _apply_persisted_totals(record: MonthlyRecord, totals: dict[str, float]) -> None:
    record.total_liquid = totals["total_liquid"]
    record.total_invested = totals["total_invested"]
    record.total_net_worth = totals["total_net_worth"]


def _to_dto(
    record: MonthlyRecord,
    previous_net_worth: float | None,
    previous_total_invested: float | None,
) -> MonthlyRecordDto:
    total_liquid = float(record.total_liquid)
    total_invested = float(record.total_invested)
    total_net_worth = float(record.total_net_worth)
    invested_percentage = (total_invested / total_net_worth * 100) if total_net_worth else 0.0
    monthly_diff = total_net_worth - previous_net_worth if previous_net_worth is not None else None
    invested_diff = (
        total_invested - previous_total_invested if previous_total_invested is not None else None
    )

    return MonthlyRecordDto(
        id=record.id,
        year=record.year,
        month=record.month,
        created_at=record.created_at,
        balances=record.balances,
        hybrid_accounts=record.hybrid_accounts,
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
    record: MonthlyRecord | None,
    db: Session,
) -> MonthlyRecordResponse:
    prev_year, prev_month = _previous_year_month(year, month)
    previous_record = _get_record(db, prev_year, prev_month)
    previous_net_worth = _persisted_net_worth(previous_record)
    previous_total_invested = _persisted_total_invested(previous_record)

    if record is None:
        return MonthlyRecordResponse(
            exists=False,
            year=year,
            month=month,
            record=None,
            previous_net_worth=previous_net_worth,
            previous_total_invested=previous_total_invested,
        )

    return MonthlyRecordResponse(
        exists=True,
        year=year,
        month=month,
        record=_to_dto(record, previous_net_worth, previous_total_invested),
        previous_net_worth=previous_net_worth,
        previous_total_invested=previous_total_invested,
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
        if entity_type not in (EntityType.LIQUID, EntityType.INVESTED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La entidad '{balance.entity_id}' debe ser LIQUID o INVESTED",
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


def _resolve_hybrid_invested(
    db: Session,
    *,
    year: int,
    month: int,
    hybrid_balances: list,
    entities_by_id: dict[str, Entity],
) -> list[tuple[str, float, float]]:
    """Devuelve (entity_id, liquid_amount, cumulative_invested) listo para persistir."""
    resolved: list[tuple[str, float, float]] = []
    for hybrid in hybrid_balances:
        entity = entities_by_id[hybrid.entity_id]
        liquid = float(hybrid.liquid_amount)
        if uses_ledger(entity):
            invested = compute_cumulative_invested(db, hybrid.entity_id, year, month, liquid)
        else:
            invested = float(hybrid.invested_amount or 0)
        resolved.append((hybrid.entity_id, liquid, invested))
    return resolved


def _upsert_record_balances(
    db: Session,
    *,
    year: int,
    month: int,
    simple_balances: list,
    hybrid_balances: list,
    totals: dict[str, float],
) -> MonthlyRecord:
    record = _get_record(db, year, month)
    if record is None:
        record = MonthlyRecord(year=year, month=month)
        db.add(record)
        db.flush()
    else:
        record.balances.clear()
        record.hybrid_accounts.clear()
        db.flush()

    _apply_persisted_totals(record, totals)

    for balance in simple_balances:
        amount = balance.amount if hasattr(balance, "amount") else balance.balance_amount
        record.balances.append(
            MonthlyEntityBalance(entity_id=balance.entity_id, balance_amount=amount)
        )

    entity_ids = {h.entity_id for h in hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids) if entity_ids else {}
    resolved_hybrids = _resolve_hybrid_invested(
        db, year=year, month=month, hybrid_balances=hybrid_balances, entities_by_id=entities_by_id
    )

    for entity_id, liquid, invested in resolved_hybrids:
        record.hybrid_accounts.append(
            MonthlyHybridAccount(
                entity_id=entity_id,
                liquid_amount=liquid,
                cumulative_invested=invested,
            )
        )

    db.commit()
    saved = _get_record(db, year, month)
    assert saved is not None
    return saved


@router.get("/timeline", response_model=TimelineResponse)
def get_records_timeline(db: Session = Depends(get_db)) -> TimelineResponse:
    """Serie temporal mes a mes con patrimonio e invertido persistidos."""
    stmt = select(MonthlyRecord).order_by(MonthlyRecord.year, MonthlyRecord.month)
    records = list(db.scalars(stmt).all())

    points: list[TimelinePoint] = []
    previous_net_worth: float | None = None
    previous_invested: float | None = None

    for record in records:
        net_worth = float(record.total_net_worth)
        invested = float(record.total_invested)
        points.append(
            TimelinePoint(
                year=record.year,
                month=record.month,
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
    record = _get_record(db, year, month)
    return _build_response(year=year, month=month, record=record, db=db)


def _patch_hybrid_balances(
    db: Session,
    *,
    year: int,
    month: int,
    hybrid_balances: list,
) -> MonthlyRecord:
    """Crea o actualiza filas en monthly_hybrid_accounts y recalcula monthly_records."""
    record = _get_record(db, year, month)
    if record is None:
        record = MonthlyRecord(year=year, month=month)
        db.add(record)
        db.flush()

    entity_ids = {h.entity_id for h in hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_balance_entity_types([], hybrid_balances, entities_by_id)

    resolved_hybrids = _resolve_hybrid_invested(
        db,
        year=year,
        month=month,
        hybrid_balances=hybrid_balances,
        entities_by_id=entities_by_id,
    )
    existing_by_entity = {h.entity_id: h for h in record.hybrid_accounts}

    for entity_id, liquid, invested in resolved_hybrids:
        existing = existing_by_entity.get(entity_id)
        if existing is not None:
            existing.liquid_amount = liquid
            existing.cumulative_invested = invested
        else:
            record.hybrid_accounts.append(
                MonthlyHybridAccount(
                    entity_id=entity_id,
                    liquid_amount=liquid,
                    cumulative_invested=invested,
                )
            )

    db.flush()
    saved = _get_record(db, year, month)
    assert saved is not None
    totals = compute_totals_from_record(saved)
    _apply_persisted_totals(saved, totals)
    db.commit()
    saved = _get_record(db, year, month)
    assert saved is not None
    return saved


@router.patch("/{year}/{month}/hybrids", response_model=MonthlyRecordResponse)
def patch_hybrid_balances(
    year: int,
    month: int,
    payload: HybridBalancesPatch,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Actualiza líquido/invertido de híbridas sin tocar monthly_entity_balances."""
    _validate_month(month)
    record = _patch_hybrid_balances(
        db,
        year=year,
        month=month,
        hybrid_balances=payload.hybrid_balances,
    )
    return _build_response(year=year, month=month, record=record, db=db)


@router.post("/{year}/{month}", response_model=MonthlyRecordResponse)
def upsert_monthly_record(
    year: int,
    month: int,
    payload: MonthlyRecordUpsert,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Crea o actualiza los balances (simples + híbridos) de un mes y persiste los totales."""
    _validate_month(month)

    entity_ids = {b.entity_id for b in payload.balances} | {h.entity_id for h in payload.hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_balance_entity_types(payload.balances, payload.hybrid_balances, entities_by_id)

    resolved_hybrids = _resolve_hybrid_invested(
        db,
        year=year,
        month=month,
        hybrid_balances=payload.hybrid_balances,
        entities_by_id=entities_by_id,
    )
    hybrid_for_totals = [
        HybridBalanceImport(entity_id=eid, liquid_amount=liq, invested_amount=inv)
        for eid, liq, inv in resolved_hybrids
    ]
    totals = compute_totals_from_simple_balances(payload.balances, entities_by_id, hybrid_for_totals)

    record = _upsert_record_balances(
        db,
        year=year,
        month=month,
        simple_balances=payload.balances,
        hybrid_balances=payload.hybrid_balances,
        totals=totals,
    )
    return _build_response(year=year, month=month, record=record, db=db)


@router.delete("/{year}/{month}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monthly_record(year: int, month: int, db: Session = Depends(get_db)) -> None:
    """Elimina el registro de un mes concreto (balances e híbridos se borran en cascada)."""
    _validate_month(month)
    record = _get_record(db, year, month)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe registro para ese mes")

    db.delete(record)
    db.commit()


@router.post("/{year}/{month}/import", response_model=MonthlyRecordResponse)
def import_monthly_record(
    year: int,
    month: int,
    payload: ImportPayload,
    db: Session = Depends(get_db),
) -> MonthlyRecordResponse:
    """Importa un mes completo, valida expected_totals y persiste balances + totales."""
    _validate_month(month)

    entity_ids = {b.entity_id for b in payload.simple_balances} | {h.entity_id for h in payload.hybrid_balances}
    entities_by_id = _load_entities(db, entity_ids)
    _validate_import_payload(payload, entities_by_id)

    resolved_hybrids = _resolve_hybrid_invested(
        db,
        year=year,
        month=month,
        hybrid_balances=payload.hybrid_balances,
        entities_by_id=entities_by_id,
    )
    hybrid_for_totals = [
        HybridBalanceImport(entity_id=eid, liquid_amount=liq, invested_amount=inv)
        for eid, liq, inv in resolved_hybrids
    ]
    totals = compute_totals_from_import(
        ImportPayload(
            simple_balances=payload.simple_balances,
            hybrid_balances=hybrid_for_totals,
            expected_totals=payload.expected_totals,
        ),
        entities_by_id,
    )
    _assert_totals_match(totals, payload)

    record = _upsert_record_balances(
        db,
        year=year,
        month=month,
        simple_balances=payload.simple_balances,
        hybrid_balances=payload.hybrid_balances,
        totals=totals,
    )
    return _build_response(year=year, month=month, record=record, db=db)
