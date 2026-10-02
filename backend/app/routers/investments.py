import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
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
    CategoryAssetDisplayOrderUpdate,
    CategoryDetailResponse,
    CategoryInvestmentsUpsert,
    CategoryOverview,
    InvestmentCategoryRead,
    InvestmentOverviewResponse,
    LinkedInvestedTotalResponse,
)
from app.services.asset_sales import asset_type_ids_with_sale_in_month
from app.services.asset_transactions import transaction_totals_by_asset_type
from app.services.fx_converter import amount_to_eur, get_usd_to_eur_rate
from app.services.linked_asset_investments import sum_linked_asset_investments_eur
from app.services.market_price_service import market_price_service

router = APIRouter(prefix="/api/investment", tags=["investment"])

# Acciones: el total de categoría se calcula solo a partir de sus activos.
COMPUTED_CATEGORY_IDS = {"acciones"}


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _round8_units(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.00000001")))


def _pick_canonical_monthly_rows(
    rows: list[MonthlyAssetInvestment],
) -> dict[UUID, MonthlyAssetInvestment]:
    """Si hay filas duplicadas (mismo activo/mes), queda la de `last_update` más reciente."""
    canonical: dict[UUID, MonthlyAssetInvestment] = {}
    for row in rows:
        previous = canonical.get(row.asset_type_id)
        if previous is None:
            canonical[row.asset_type_id] = row
            continue
        row_ts = row.last_update or datetime.min
        prev_ts = previous.last_update or datetime.min
        if row_ts >= prev_ts:
            canonical[row.asset_type_id] = row
    return canonical


def _monthly_rows_for_asset_month(
    db: Session, *, year: int, month: int, asset_type_id: UUID
) -> list[MonthlyAssetInvestment]:
    return list(
        db.scalars(
            select(MonthlyAssetInvestment).where(
                MonthlyAssetInvestment.year == year,
                MonthlyAssetInvestment.month == month,
                MonthlyAssetInvestment.asset_type_id == asset_type_id,
            )
        ).all()
    )


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

    next_order = db.scalar(
        select(func.coalesce(func.max(AssetType.display_order), 0)).where(
            AssetType.category_id == payload.category_id,
            AssetType.is_active.is_(True),
        )
    )
    asset = AssetType(
        category_id=payload.category_id,
        name=payload.name,
        ticker=payload.ticker,
        currency=payload.currency,
        display_order=int(next_order or 0) + 1,
        entity_id=payload.entity_id,
        price_source=payload.price_source,
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
    previous_ticker = asset.ticker
    previous_price_source = asset.price_source
    if "ticker" in updates:
        asset.ticker = updates["ticker"]
    if "currency" in updates:
        asset.currency = updates["currency"]
    if "entity_id" in updates:
        _validate_asset_entity_link(db, updates["entity_id"])
        asset.entity_id = updates["entity_id"]
    if "price_source" in updates:
        asset.price_source = updates["price_source"]
    if "display_order" in updates:
        asset.display_order = updates["display_order"]

    db.commit()
    db.refresh(asset)

    if "ticker" in updates or "price_source" in updates:
        market_price_service.invalidate_ticker(previous_price_source, previous_ticker)
        market_price_service.invalidate_ticker(asset.price_source, asset.ticker)

    return asset


@router.put("/categories/{category_id}/asset-types/display-order", response_model=list[AssetTypeRead])
def update_category_asset_display_order(
    category_id: str, payload: CategoryAssetDisplayOrderUpdate, db: Session = Depends(get_db)
) -> list[AssetType]:
    """Actualiza el orden de visualización de los activos activos de una categoría."""
    _get_category_or_404(db, category_id)

    assets = list(
        db.scalars(
            select(AssetType)
            .where(AssetType.category_id == category_id, AssetType.is_active.is_(True))
            .order_by(AssetType.display_order)
        ).all()
    )
    assets_by_id = {asset.id: asset for asset in assets}
    expected_ids = set(assets_by_id.keys())
    submitted_ids = {item.asset_type_id for item in payload.items}

    if submitted_ids != expected_ids:
        missing = expected_ids - submitted_ids
        extra = submitted_ids - expected_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar el orden de todos los activos de la categoría.",
            )
        if extra:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hay activos en la petición que no pertenecen a esta categoría.",
            )

    orders = [item.display_order for item in payload.items]
    if len(set(orders)) != len(orders):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cada activo debe tener un número de orden distinto dentro de la categoría.",
        )

    for item in payload.items:
        assets_by_id[item.asset_type_id].display_order = item.display_order

    db.commit()
    return list(
        db.scalars(
            select(AssetType)
            .where(AssetType.category_id == category_id, AssetType.is_active.is_(True))
            .order_by(AssetType.display_order)
        ).all()
    )


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

    category_overviews: list[CategoryOverview] = []
    total_invested = Decimal("0")
    for cat in categories:
        is_computed = cat.id in COMPUTED_CATEGORY_IDS
        allocated = computed.get(cat.id, 0.0)
        if cat.id in saved:
            amount = max(saved[cat.id], allocated)
        else:
            amount = allocated
        total_invested += Decimal(str(amount))

        category_overviews.append(
            CategoryOverview(
                category_id=cat.id,
                name=cat.name,
                color=cat.color,
                amount_eur=amount,
                percentage=0.0,  # se recalcula abajo con el total del detalle
                editable=not is_computed,
                saved_this_month=cat.id in saved,
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
    if asset_type_ids:
        saved_assets = _pick_canonical_monthly_rows(
            list(
                db.scalars(
                    select(MonthlyAssetInvestment).where(
                        MonthlyAssetInvestment.year == year,
                        MonthlyAssetInvestment.month == month,
                        MonthlyAssetInvestment.asset_type_id.in_(asset_type_ids),
                    )
                ).all()
            )
        )

    tx_totals_by_asset = transaction_totals_by_asset_type(db, asset_type_ids, year=year, month=month)
    asset_ids_with_sale = asset_type_ids_with_sale_in_month(db, asset_type_ids, year, month)

    assets_detail: list[AssetInvestmentDetail] = []
    allocated = Decimal("0")
    has_usd_assets = any(a.currency == "USD" for a in asset_types)
    for asset in asset_types:
        saved = saved_assets.get(asset.id)
        amount = float(saved.amount) if saved else 0.0
        amount_eur = amount_to_eur(amount, asset.currency, year, month)
        allocated += Decimal(str(amount_eur))
        tx_totals = tx_totals_by_asset.get(asset.id)
        assets_detail.append(
            AssetInvestmentDetail(
                asset_type_id=asset.id,
                name=asset.name,
                ticker=asset.ticker,
                display_order=asset.display_order,
                currency=asset.currency,
                entity_id=asset.entity_id,
                entity_name=asset.entity.name if asset.entity else None,
                amount=amount,
                amount_eur=amount_eur,
                units=_round8_units(saved.units) if saved and saved.units is not None else None,
                has_transactions=tx_totals is not None,
                has_sale_this_month=asset.id in asset_ids_with_sale,
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

    if not payload.assets:
        logger.warning(
            "POST upsert_category_assets: category=%s %s-%02d sin activos en payload "
            "(solo puede actualizar total de categoría)",
            category_id,
            year,
            month,
        )

    logger.info(
        "POST upsert_category_assets: category=%s %s-%02d payload.assets=%s category_amount_eur=%s",
        category_id,
        year,
        month,
        [
            {
                "asset_type_id": str(item.asset_type_id),
                "amount": item.amount,
                "units": item.units,
            }
            for item in payload.assets
        ],
        payload.category_amount_eur,
    )

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
        asset_name = asset_types_by_id.get(item.asset_type_id)
        asset_label = asset_name.name if asset_name else str(item.asset_type_id)
        matching_rows = _monthly_rows_for_asset_month(
            db, year=year, month=month, asset_type_id=item.asset_type_id
        )
        if len(matching_rows) > 1:
            logger.warning(
                "monthly_asset_investments: %s filas duplicadas para %s (%s) %s-%02d; "
                "se actualizarán todas",
                len(matching_rows),
                asset_label,
                item.asset_type_id,
                year,
                month,
            )

        manual_touch = datetime.now()
        if matching_rows:
            action = "actualizado"
            for row in matching_rows:
                logger.info(
                    "monthly_asset_investments ANTES id=%s %s (%s) %s-%02d: amount=%s units=%s last_update=%s",
                    row.id,
                    asset_label,
                    item.asset_type_id,
                    year,
                    month,
                    row.amount,
                    row.units,
                    row.last_update,
                )
                row.amount = item.amount
                row.units = item.units
                row.last_update = manual_touch
        else:
            action = "creado"
            db.add(
                MonthlyAssetInvestment(
                    year=year,
                    month=month,
                    asset_type_id=item.asset_type_id,
                    amount=item.amount,
                    units=item.units,
                    last_update=manual_touch,
                )
            )
        logger.info(
            "monthly_asset_investments %s manualmente: %s (%s) %s-%02d amount=%s units=%s",
            action,
            asset_label,
            item.asset_type_id,
            year,
            month,
            item.amount,
            item.units,
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

    for item in payload.assets:
        asset_meta = asset_types_by_id.get(item.asset_type_id)
        asset_label = asset_meta.name if asset_meta else str(item.asset_type_id)
        after_rows = _monthly_rows_for_asset_month(
            db, year=year, month=month, asset_type_id=item.asset_type_id
        )
        logger.info(
            "monthly_asset_investments DESPUÉS commit: %s (%s) %s-%02d → %s fila(s) %s",
            asset_label,
            item.asset_type_id,
            year,
            month,
            len(after_rows),
            [
                {
                    "id": str(r.id),
                    "amount": float(r.amount),
                    "units": _round8_units(r.units) if r.units is not None else None,
                    "last_update": r.last_update.isoformat() if r.last_update else None,
                }
                for r in after_rows
            ],
        )

    detail = _build_category_detail(db, year, month, category)
    for asset_detail in detail.assets:
        if payload.assets and any(
            item.asset_type_id == asset_detail.asset_type_id for item in payload.assets
        ):
            logger.info(
                "POST upsert respuesta API: %s amount=%s units=%s amount_eur=%s",
                asset_detail.name,
                asset_detail.amount,
                asset_detail.units,
                asset_detail.amount_eur,
            )
    return detail
