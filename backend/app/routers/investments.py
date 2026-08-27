from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.models.investment_category import InvestmentCategory
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.models.monthly_category_investment import MonthlyCategoryInvestment
from app.models.monthly_entity_balance import MonthlyEntityBalance
from app.models.monthly_hybrid_account import MonthlyHybridAccount
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
)
from app.services.fx_converter import amount_to_eur, get_usd_to_eur_rate

router = APIRouter(prefix="/api/investment", tags=["investment"])

# Categorías cuyo total NO se introduce a mano: se calcula sumando sus activos.
# Fondos y Crypto son libres (total manual + reparto por activos que debe cuadrar con ese total).
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
    stmt = select(MonthlyRecord).where(MonthlyRecord.year == year, MonthlyRecord.month == month)
    return db.scalars(stmt).first()


def _get_categories(db: Session) -> list[InvestmentCategory]:
    stmt = select(InvestmentCategory).order_by(InvestmentCategory.display_order)
    return list(db.scalars(stmt).all())


def _get_category_or_404(db: Session, category_id: str) -> InvestmentCategory:
    category = db.get(InvestmentCategory, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Categoría '{category_id}' no encontrada")
    return category


def _entity_category_breakdown(db: Session, record: MonthlyRecord | None) -> dict[str, dict]:
    """Suma, por categoría, el importe ya conocido de las entidades con default_category_id
    fijado (p.ej. KuCoin → crypto), para usarlo como valor sugerido al repartir el mes."""
    if record is None:
        return {}

    totals: dict[str, Decimal] = {}
    names: dict[str, list[str]] = {}

    simple_stmt = (
        select(Entity.default_category_id, Entity.name, MonthlyEntityBalance.balance_amount)
        .join(MonthlyEntityBalance, MonthlyEntityBalance.entity_id == Entity.id)
        .where(
            MonthlyEntityBalance.record_id == record.id,
            Entity.default_category_id.is_not(None),
            Entity.entity_type == EntityType.INVESTED,
        )
    )
    for category_id, name, amount in db.execute(simple_stmt).all():
        totals[category_id] = totals.get(category_id, Decimal("0")) + Decimal(str(amount))
        names.setdefault(category_id, []).append(name)

    hybrid_stmt = (
        select(Entity.default_category_id, Entity.name, MonthlyHybridAccount.cumulative_invested)
        .join(MonthlyHybridAccount, MonthlyHybridAccount.entity_id == Entity.id)
        .where(
            MonthlyHybridAccount.record_id == record.id,
            Entity.default_category_id.is_not(None),
        )
    )
    for category_id, name, amount in db.execute(hybrid_stmt).all():
        totals[category_id] = totals.get(category_id, Decimal("0")) + Decimal(str(amount))
        names.setdefault(category_id, []).append(name)

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
    asset.monthly_contribution = payload.monthly_contribution
    db.commit()
    db.refresh(asset)
    return asset


def _build_overview(db: Session, year: int, month: int) -> InvestmentOverviewResponse:
    categories = _get_categories(db)
    record = _find_record(db, year, month)

    saved = _category_totals(db, year, month)
    computed = _computed_category_totals(db, year, month)

    prev_year, prev_month = _previous_year_month(year, month)
    prev_saved = _category_totals(db, prev_year, prev_month)
    prev_computed = _computed_category_totals(db, prev_year, prev_month)

    entity_breakdown = _entity_category_breakdown(db, record)

    category_overviews: list[CategoryOverview] = []
    total_invested = Decimal("0")
    for cat in categories:
        is_computed = cat.id in COMPUTED_CATEGORY_IDS
        amount = computed.get(cat.id, 0.0) if is_computed else saved.get(cat.id, 0.0)
        previous_amount = prev_computed.get(cat.id) if is_computed else prev_saved.get(cat.id)
        total_invested += Decimal(str(amount))

        entity_amount = entity_breakdown.get(cat.id, {}).get("amount", 0.0)
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
                entity_names=entity_breakdown.get(cat.id, {}).get("names", []),
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
        has_month_record=record is not None,
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
        suggested_amount = _asset_suggested_amount(prev_amount, monthly_contribution)
        assets_detail.append(
            AssetInvestmentDetail(
                asset_type_id=asset.id,
                name=asset.name,
                ticker=asset.ticker,
                currency=asset.currency,
                amount=amount,
                amount_eur=amount_eur,
                units=float(saved.units) if saved and saved.units is not None else None,
                previous_amount=prev_amount,
                previous_units=float(prev.units) if prev and prev.units is not None else None,
                monthly_contribution=monthly_contribution,
                suggested_amount=suggested_amount,
            )
        )

    fx_usd_to_eur = get_usd_to_eur_rate(year, month) if has_usd_assets else None

    if is_computed:
        # El total NACE del detalle: no hay valor manual que cuadrar, siempre coincide.
        category_amount = _round2(allocated)
    else:
        category_row = db.scalars(
            select(MonthlyCategoryInvestment).where(
                MonthlyCategoryInvestment.year == year,
                MonthlyCategoryInvestment.month == month,
                MonthlyCategoryInvestment.category_id == category.id,
            )
        ).first()
        category_amount = float(category_row.amount_eur) if category_row else 0.0

    others = _round2(Decimal(str(category_amount)) - allocated)

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
    db.commit()

    return _build_category_detail(db, year, month, category)
