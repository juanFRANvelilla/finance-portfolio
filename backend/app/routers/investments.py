from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.models.fiat_deposit import FiatDeposit
from app.models.investment_category import InvestmentCategory
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.models.monthly_category_investment import MonthlyCategoryInvestment
from app.models.monthly_record import MonthlyRecord
from app.schemas.investment import (
    AssetInvestmentDetail,
    AssetInvestmentsUpsert,
    AssetTypeCreate,
    AssetTypeRead,
    AssetTypeUpdate,
    CategoryDetailResponse,
    CategoryInvestmentsUpsert,
    CategoryOverview,
    InvestmentCategoryRead,
    InvestmentOverviewResponse,
    LinkedInvestedTotalResponse,
)
from app.services.asset_transactions import transaction_totals_by_asset_type
from app.services.fiat_deposits import fiat_deposit_total_for_entity
from app.services.fx_converter import amount_to_eur, eur_to_native, get_usd_to_eur_rate
from app.services.linked_asset_investments import sum_linked_asset_investments_eur

router = APIRouter(prefix="/api/investment", tags=["investment"])

# Categoría que recibe la previsión estática por depósitos fiat (p. ej. KuCoin → Crypto).
FIAT_DEPOSIT_PREVIEW_CATEGORY_ID = "crypto"
# Acciones: el total de categoría se calcula solo a partir de sus activos.
COMPUTED_CATEGORY_IDS = {"acciones"}

# Categorías cuyos activos llevan además nº de títulos (units).
HAS_UNITS_CATEGORY_IDS = {"acciones"}


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _find_record(db: Session, year: int, month: int) -> MonthlyRecord | None:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(MonthlyRecord)
        .options(
            selectinload(MonthlyRecord.balances),
            selectinload(MonthlyRecord.hybrid_accounts),
        )
        .where(MonthlyRecord.year == year, MonthlyRecord.month == month)
    )
    return db.scalars(stmt).first()


def _get_categories(db: Session) -> list[InvestmentCategory]:
    stmt = select(InvestmentCategory).order_by(InvestmentCategory.display_order)
    return list(db.scalars(stmt).all())


def _get_category_or_404(db: Session, category_id: str) -> InvestmentCategory:
    category = db.get(InvestmentCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Categoría '{category_id}' no encontrada")
    return category


def _previous_entity_balance(db: Session, entity_id: str, year: int, month: int) -> float | None:
    """Saldo estático de la entidad en el mes anterior (panel principal)."""
    prev_year, prev_month = _previous_year_month(year, month)
    record = _find_record(db, prev_year, prev_month)
    if record is None:
        return None

    entity = db.get(Entity, entity_id)
    if entity is None:
        return None

    if entity.entity_type == EntityType.HYBRID:
        hybrid = next((h for h in record.hybrid_accounts if h.entity_id == entity_id), None)
        if hybrid is None:
            return None
        total = Decimal(str(hybrid.liquid_amount)) + Decimal(str(hybrid.cumulative_invested))
        return _round2(total)

    balance = next((b for b in record.balances if b.entity_id == entity_id), None)
    if balance is None:
        return None
    return _round2(Decimal(str(balance.balance_amount)))


def _entity_deposit_preview(db: Session, entity_id: str, year: int, month: int) -> float | None:
    """Previsión estática por entidad: P1 suma fiat_deposits, P2 saldo mes anterior."""
    fiat_total = fiat_deposit_total_for_entity(db, entity_id)
    if fiat_total is not None:
        return fiat_total

    return _previous_entity_balance(db, entity_id, year, month)


def _fiat_deposit_category_breakdown(db: Session, year: int, month: int) -> dict[str, dict]:
    """Previsión Crypto desde entidades INVESTED con filas en fiat_deposits."""
    entities = list(
        db.scalars(
            select(Entity).where(Entity.is_active.is_(True), Entity.entity_type == EntityType.INVESTED)
        ).all()
    )

    totals: dict[str, Decimal] = {}
    names: dict[str, list[str]] = {}

    for entity in entities:
        has_deposits = db.scalar(
            select(func.count())
            .select_from(FiatDeposit)
            .where(FiatDeposit.entity_id == entity.id)
        )
        if not has_deposits:
            continue

        preview = _entity_deposit_preview(db, entity.id, year, month)
        if preview is None or preview <= 0:
            continue

        category_id = FIAT_DEPOSIT_PREVIEW_CATEGORY_ID
        totals[category_id] = totals.get(category_id, Decimal("0")) + Decimal(str(preview))
        names.setdefault(category_id, []).append(entity.name)

    return {
        cat_id: {"amount": _round2(total), "names": names.get(cat_id, [])} for cat_id, total in totals.items()
    }


def _category_totals(db: Session, year: int, month: int) -> dict[str, float]:
    """Totales guardados a mano en monthly_category_investments (Fondos/Crypto) para ese mes."""
    stmt = select(MonthlyCategoryInvestment).where(
        MonthlyCategoryInvestment.year == year, MonthlyCategoryInvestment.month == month
    )
    return {row.category_id: float(row.amount_eur) for row in db.scalars(stmt).all()}


def _computed_category_totals(db: Session, year: int, month: int) -> dict[str, float]:
    """Totales calculados sumando activos convertidos a EUR, agrupados por categoría."""
    stmt = (
        select(AssetType.category_id, AssetType.currency, MonthlyAssetInvestment.amount)
        .join(MonthlyAssetInvestment, MonthlyAssetInvestment.asset_type_id == AssetType.id)
        .where(MonthlyAssetInvestment.year == year, MonthlyAssetInvestment.month == month)
    )
    totals: dict[str, Decimal] = {}
    for category_id, currency, amount in db.execute(stmt).all():
        eur = Decimal(str(amount_to_eur(float(amount), currency, year, month)))
        totals[category_id] = totals.get(category_id, Decimal("0")) + eur
    return {cat_id: _round2(total) for cat_id, total in totals.items()}


def _category_monthly_contributions_eur(db: Session, category_id: str, year: int, month: int) -> float:
    """Suma en EUR las aportaciones mensuales fijas de los activos activos de una categoría."""
    assets = list(
        db.scalars(
            select(AssetType).where(
                AssetType.category_id == category_id,
                AssetType.is_active.is_(True),
                AssetType.monthly_contribution.is_not(None),
            )
        ).all()
    )
    total = Decimal("0")
    for asset in assets:
        contribution = float(asset.monthly_contribution or 0)
        if contribution <= 0:
            continue
        total += Decimal(str(amount_to_eur(contribution, asset.currency, year, month)))
    return _round2(total)


def _asset_suggested_amount(previous_amount: float | None, monthly_contribution: float | None) -> float:
    base = Decimal(str(previous_amount if previous_amount is not None else 0))
    contribution = Decimal(str(monthly_contribution if monthly_contribution is not None else 0))
    return _round2(base + contribution)


def _asset_preview_from_transactions(
    *,
    tx_totals: dict[str, float] | None,
    previous_amount: float | None,
    monthly_contribution: float | None,
    currency: str,
    year: int,
    month: int,
    include_units: bool,
) -> tuple[float, float | None]:
    """P1: suma de asset_transactions; P2: mes anterior + aportación mensual."""
    if tx_totals and tx_totals.get("invested_amount_eur", 0) > 0:
        suggested_amount = eur_to_native(tx_totals["invested_amount_eur"], currency, year, month)
        suggested_units = tx_totals.get("asset_amount") if include_units else None
        return suggested_amount, suggested_units

    return _asset_suggested_amount(previous_amount, monthly_contribution), None


def _category_suggested_amount_eur(
    *,
    previous_amount_eur: float | None,
    entity_amount_eur: float,
    contributions_eur: float,
) -> float:
    if entity_amount_eur > 0:
        return entity_amount_eur
    base = Decimal(str(previous_amount_eur if previous_amount_eur is not None else 0))
    return _round2(base + Decimal(str(contributions_eur)))


def _get_entity_or_404(db: Session, entity_id: str) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entidad '{entity_id}' no encontrada")
    return entity


def _validate_asset_entity_link(db: Session, entity_id: str | None) -> None:
    if entity_id is None:
        return
    entity = _get_entity_or_404(db, entity_id)
    if entity.entity_type not in (EntityType.INVESTED, EntityType.HYBRID):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La entidad '{entity_id}' debe ser de tipo INVESTED o HYBRID",
        )


@router.get("/categories", response_model=list[InvestmentCategoryRead])
def list_investment_categories(db: Session = Depends(get_db)) -> list[InvestmentCategory]:
    return _get_categories(db)


@router.get("/asset-types", response_model=list[AssetTypeRead])
def list_asset_types(category_id: str | None = None, db: Session = Depends(get_db)) -> list[AssetType]:
    stmt = select(AssetType).where(AssetType.is_active.is_(True)).order_by(AssetType.display_order)
    if category_id:
        stmt = stmt.where(AssetType.category_id == category_id)
    return list(db.scalars(stmt).all())


@router.post("/asset-types", response_model=AssetTypeRead, status_code=status.HTTP_201_CREATED)
def create_asset_type(payload: AssetTypeCreate, db: Session = Depends(get_db)) -> AssetType:
    _get_category_or_404(db, payload.category_id)
    _validate_asset_entity_link(db, payload.entity_id)

    existing = db.scalars(select(AssetType).where(AssetType.name == payload.name)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe un activo llamado '{payload.name}'"
        )

    asset = AssetType(
        category_id=payload.category_id,
        name=payload.name,
        ticker=payload.ticker,
        currency=payload.currency,
        monthly_contribution=payload.monthly_contribution,
        entity_id=payload.entity_id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/asset-types/{asset_type_id}", response_model=AssetTypeRead)
def update_asset_type(
    asset_type_id: UUID, payload: AssetTypeUpdate, db: Session = Depends(get_db)
) -> AssetType:
    asset = db.get(AssetType, asset_type_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")

    updates = payload.model_dump(exclude_unset=True)
    if "ticker" in updates:
        asset.ticker = updates["ticker"]
    if "currency" in updates:
        asset.currency = updates["currency"]
    if "entity_id" in updates:
        _validate_asset_entity_link(db, updates["entity_id"])
        asset.entity_id = updates["entity_id"]
    if "monthly_contribution" in updates:
        asset.monthly_contribution = updates["monthly_contribution"]

    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{year}/{month}/entities/{entity_id}/linked-invested-total", response_model=LinkedInvestedTotalResponse)
def get_entity_linked_invested_total(
    year: int, month: int, entity_id: str, db: Session = Depends(get_db)
) -> LinkedInvestedTotalResponse:
    """Suma en EUR los importes de monthly_asset_investments de activos vinculados a la entidad."""
    entity = _get_entity_or_404(db, entity_id)
    if entity.entity_type != EntityType.HYBRID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La entidad '{entity_id}' no es híbrida",
        )

    totals = sum_linked_asset_investments_eur(db, entity_id, year, month)
    return LinkedInvestedTotalResponse(
        entity_id=entity_id,
        year=year,
        month=month,
        total_eur=float(totals["total_eur"]),
        asset_count=int(totals["asset_count"]),
    )


def _build_overview(db: Session, year: int, month: int) -> InvestmentOverviewResponse:
    categories = _get_categories(db)

    saved = _category_totals(db, year, month)
    computed = _computed_category_totals(db, year, month)

    prev_year, prev_month = _previous_year_month(year, month)
    prev_saved = _category_totals(db, prev_year, prev_month)
    prev_computed = _computed_category_totals(db, prev_year, prev_month)

    deposit_breakdown = _fiat_deposit_category_breakdown(db, year, month)

    category_overviews: list[CategoryOverview] = []
    total_invested = Decimal("0")
    for cat in categories:
        is_computed = cat.id in COMPUTED_CATEGORY_IDS
        allocated = computed.get(cat.id, 0.0)
        if cat.id in saved:
            amount = max(saved[cat.id], allocated)
        else:
            amount = allocated
        previous_amount = prev_saved.get(cat.id) if cat.id in prev_saved else prev_computed.get(cat.id)
        total_invested += Decimal(str(amount))

        entity_amount = deposit_breakdown.get(cat.id, {}).get("amount", 0.0)
        contributions_eur = _category_monthly_contributions_eur(db, cat.id, year, month)
        suggested_amount_eur = _category_suggested_amount_eur(
            previous_amount_eur=previous_amount,
            entity_amount_eur=entity_amount,
            contributions_eur=contributions_eur,
        )

        category_overviews.append(
            CategoryOverview(
                category_id=cat.id,
                name=cat.name,
                color=cat.color,
                amount_eur=amount,
                percentage=0.0,  # se recalcula abajo con el total del detalle
                previous_amount_eur=previous_amount,
                entity_amount_eur=entity_amount,
                entity_names=deposit_breakdown.get(cat.id, {}).get("names", []),
                editable=not is_computed,
                saved_this_month=cat.id in saved,
                suggested_amount_eur=suggested_amount_eur,
                monthly_contributions_eur=contributions_eur,
            )
        )

    total_invested_f = _round2(total_invested)
    for overview in category_overviews:
        overview.percentage = (
            round((overview.amount_eur / total_invested_f * 100), 2) if total_invested_f else 0.0
        )

    return InvestmentOverviewResponse(
        year=year,
        month=month,
        total_invested=total_invested_f,
        has_month_record=_find_record(db, year, month) is not None,
        categories=category_overviews,
        previous_year=prev_year,
        previous_month=prev_month,
    )


@router.get("/{year}/{month}", response_model=InvestmentOverviewResponse)
def get_investment_overview(year: int, month: int, db: Session = Depends(get_db)) -> InvestmentOverviewResponse:
    """Resumen de inversión de un mes.

    `total_invested` es la suma de las categorías registradas aquí (Fondos + Crypto + Acciones),
    independiente del total invertido del panel principal (monthly_records).
    """
    return _build_overview(db, year, month)


@router.post("/{year}/{month}/categories", response_model=InvestmentOverviewResponse)
def upsert_category_investments(
    year: int, month: int, payload: CategoryInvestmentsUpsert, db: Session = Depends(get_db)
) -> InvestmentOverviewResponse:
    """Guarda el importe manual y libre de las categorías editables (Fondos/Crypto).
    Sin bloqueos por cuadre de totales: máxima flexibilidad para registrar en cualquier momento."""
    categories = _get_categories(db)
    valid_ids = {cat.id for cat in categories}
    computed_ids = {cat.id for cat in categories if cat.id in COMPUTED_CATEGORY_IDS}

    provided_ids = {item.category_id for item in payload.categories}

    unknown_ids = provided_ids - valid_ids
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Categorías desconocidas: {sorted(unknown_ids)}"
        )

    computed_provided = provided_ids & computed_ids
    if computed_provided:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estas categorías se calculan automáticamente a partir de sus activos: {sorted(computed_provided)}",
        )

    for item in payload.categories:
        existing = db.scalars(
            select(MonthlyCategoryInvestment).where(
                MonthlyCategoryInvestment.year == year,
                MonthlyCategoryInvestment.month == month,
                MonthlyCategoryInvestment.category_id == item.category_id,
            )
        ).first()
        if existing is not None:
            existing.amount_eur = item.amount_eur
        else:
            db.add(
                MonthlyCategoryInvestment(
                    year=year, month=month, category_id=item.category_id, amount_eur=item.amount_eur
                )
            )
    db.commit()

    return _build_overview(db, year, month)


def _build_category_detail(db: Session, year: int, month: int, category: InvestmentCategory) -> CategoryDetailResponse:
    is_computed = category.id in COMPUTED_CATEGORY_IDS
    has_units = category.id in HAS_UNITS_CATEGORY_IDS

    asset_types = list(
        db.scalars(
            select(AssetType)
            .options(joinedload(AssetType.entity))
            .where(AssetType.category_id == category.id, AssetType.is_active.is_(True))
            .order_by(AssetType.display_order)
        ).all()
    )
    asset_type_ids = [a.id for a in asset_types]

    saved_assets: dict[UUID, MonthlyAssetInvestment] = {}
    prev_assets: dict[UUID, MonthlyAssetInvestment] = {}
    if asset_type_ids:
        saved_assets = {
            row.asset_type_id: row
            for row in db.scalars(
                select(MonthlyAssetInvestment).where(
                    MonthlyAssetInvestment.year == year,
                    MonthlyAssetInvestment.month == month,
                    MonthlyAssetInvestment.asset_type_id.in_(asset_type_ids),
                )
            ).all()
        }

        prev_year, prev_month = _previous_year_month(year, month)
        prev_assets = {
            row.asset_type_id: row
            for row in db.scalars(
                select(MonthlyAssetInvestment).where(
                    MonthlyAssetInvestment.year == prev_year,
                    MonthlyAssetInvestment.month == prev_month,
                    MonthlyAssetInvestment.asset_type_id.in_(asset_type_ids),
                )
            ).all()
        }

    tx_totals_by_asset = transaction_totals_by_asset_type(db, asset_type_ids)

    assets_detail: list[AssetInvestmentDetail] = []
    allocated = Decimal("0")
    has_usd_assets = any(a.currency == "USD" for a in asset_types)
    for asset in asset_types:
        saved = saved_assets.get(asset.id)
        prev = prev_assets.get(asset.id)
        amount = float(saved.amount) if saved else 0.0
        amount_eur = amount_to_eur(amount, asset.currency, year, month)
        allocated += Decimal(str(amount_eur))
        prev_amount = float(prev.amount) if prev else None
        monthly_contribution = float(asset.monthly_contribution) if asset.monthly_contribution is not None else None
        suggested_amount, suggested_units = _asset_preview_from_transactions(
            tx_totals=tx_totals_by_asset.get(asset.id),
            previous_amount=prev_amount,
            monthly_contribution=monthly_contribution,
            currency=asset.currency,
            year=year,
            month=month,
            include_units=has_units,
        )
        assets_detail.append(
            AssetInvestmentDetail(
                asset_type_id=asset.id,
                name=asset.name,
                ticker=asset.ticker,
                currency=asset.currency,
                entity_id=asset.entity_id,
                entity_name=asset.entity.name if asset.entity else None,
                amount=amount,
                amount_eur=amount_eur,
                units=float(saved.units) if saved and saved.units is not None else None,
                previous_amount=prev_amount,
                previous_units=float(prev.units) if prev and prev.units is not None else None,
                monthly_contribution=monthly_contribution,
                suggested_amount=suggested_amount,
                suggested_units=suggested_units,
            )
        )

    fx_usd_to_eur = get_usd_to_eur_rate(year, month) if has_usd_assets else None

    allocated_f = _round2(allocated)
    category_row = db.scalars(
        select(MonthlyCategoryInvestment).where(
            MonthlyCategoryInvestment.year == year,
            MonthlyCategoryInvestment.month == month,
            MonthlyCategoryInvestment.category_id == category.id,
        )
    ).first()
    if category_row is not None:
        category_amount = max(float(category_row.amount_eur), allocated_f)
    else:
        category_amount = allocated_f

    others = max(0.0, _round2(Decimal(str(category_amount)) - allocated))

    return CategoryDetailResponse(
        year=year,
        month=month,
        category_id=category.id,
        category_name=category.name,
        is_computed=is_computed,
        has_units=has_units,
        category_amount_eur=category_amount,
        fx_usd_to_eur=fx_usd_to_eur,
        assets=assets_detail,
        allocated_amount_eur=_round2(allocated),
        others_amount_eur=others,
    )


@router.get("/{year}/{month}/categories/{category_id}", response_model=CategoryDetailResponse)
def get_category_detail(
    year: int, month: int, category_id: str, db: Session = Depends(get_db)
) -> CategoryDetailResponse:
    category = _get_category_or_404(db, category_id)
    return _build_category_detail(db, year, month, category)


@router.post("/{year}/{month}/categories/{category_id}/assets", response_model=CategoryDetailResponse)
def upsert_category_assets(
    year: int, month: int, category_id: str, payload: AssetInvestmentsUpsert, db: Session = Depends(get_db)
) -> CategoryDetailResponse:
    """Guarda el reparto de activos de una categoría para un mes. Sin bloqueos por totales:
    se puede registrar/actualizar en cualquier momento, con o sin datos del mes anterior."""
    category = _get_category_or_404(db, category_id)

    asset_types_by_id = {
        a.id: a for a in db.scalars(select(AssetType).where(AssetType.category_id == category.id)).all()
    }

    unknown_ids = {item.asset_type_id for item in payload.assets} - set(asset_types_by_id.keys())
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Los siguientes activos no pertenecen a la categoría '{category_id}': "
            f"{sorted(str(i) for i in unknown_ids)}",
        )

    for item in payload.assets:
        existing = db.scalars(
            select(MonthlyAssetInvestment).where(
                MonthlyAssetInvestment.year == year,
                MonthlyAssetInvestment.month == month,
                MonthlyAssetInvestment.asset_type_id == item.asset_type_id,
            )
        ).first()
        if existing is not None:
            existing.amount = item.amount
            existing.units = item.units
        else:
            db.add(
                MonthlyAssetInvestment(
                    year=year,
                    month=month,
                    asset_type_id=item.asset_type_id,
                    amount=item.amount,
                    units=item.units,
                )
            )

    allocated_eur = Decimal("0")
    saved_rows = db.scalars(
        select(MonthlyAssetInvestment)
        .join(AssetType, MonthlyAssetInvestment.asset_type_id == AssetType.id)
        .where(
            MonthlyAssetInvestment.year == year,
            MonthlyAssetInvestment.month == month,
            AssetType.category_id == category.id,
        )
    ).all()
    for saved in saved_rows:
        asset = asset_types_by_id[saved.asset_type_id]
        allocated_eur += Decimal(str(amount_to_eur(float(saved.amount), asset.currency, year, month)))

    category_row = db.scalars(
        select(MonthlyCategoryInvestment).where(
            MonthlyCategoryInvestment.year == year,
            MonthlyCategoryInvestment.month == month,
            MonthlyCategoryInvestment.category_id == category.id,
        )
    ).first()

    if payload.category_amount_eur is not None:
        requested = Decimal(str(payload.category_amount_eur))
        if requested + Decimal("0.005") < allocated_eur:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"El total de categoría ({_round2(requested):.2f} €) no puede ser inferior "
                    f"a la suma de activos ({_round2(allocated_eur):.2f} €)."
                ),
            )
        total_eur = _round2(requested)
    elif category_row is not None and Decimal(str(category_row.amount_eur)) >= allocated_eur:
        total_eur = float(category_row.amount_eur)
    else:
        total_eur = _round2(allocated_eur)

    if category_row is not None:
        category_row.amount_eur = total_eur
    else:
        db.add(
            MonthlyCategoryInvestment(
                year=year, month=month, category_id=category.id, amount_eur=total_eur
            )
        )

    db.commit()

    return _build_category_detail(db, year, month, category)
