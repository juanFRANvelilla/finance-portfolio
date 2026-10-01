"""Actualiza monthly_asset_investments a partir de asset_transactions recién insertadas.

Ver `.cursor/rules/monthly-asset-investments-sync.mdc` para el diseño completo.
Resumen de la regla:

- Solo actúa sobre fills que `insert_transactions_batch` haya insertado de
  verdad (los duplicados por `exchange_trade_id` no llegan aquí).
- Solo toca la fila de `monthly_asset_investments` del **mes natural actual**
  (`date.today()` al procesar). Entra en el snapshot solo si `executed_at` cae en
  ese mes; `transaction_date` no interviene. Sin `executed_at` no se actualiza
  la foto mensual (solo queda el registro en `asset_transactions`).
  Meses pasados/futuros respecto al mes en curso: solo `asset_transactions`.
- Si no existe fila para (activo, año, mes), se crea copiando `amount`/`units`
  del mes anterior (o 0 si tampoco existe) y sumando TODOS los fills del grupo
  (son todos nuevos, no hay nada que comparar).
- Si ya existe fila, solo se suman los fills cuyo `executed_at` sea
  ESTRICTAMENTE posterior al `last_update` actual. Si ninguno lo es, no se
  toca la fila (se asume que ya se aplicó a mano o en una pasada anterior).
- `last_update` pasa a ser el `executed_at` más tardío de lo aplicado, nunca
  la fecha de "hoy" en que corre el script.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.monthly_asset_investment import MonthlyAssetInvestment

logger = logging.getLogger(__name__)

_AMOUNT_QUANT = Decimal("0.01")
_UNITS_QUANT = Decimal("0.0001")


def _previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


@dataclass(frozen=True)
class SnapshotFill:
    """Vista mínima de un fill insertado: lo único que necesita el snapshot."""

    asset_type_id: str
    year: int
    month: int
    executed_at: datetime | None
    invested_amount: Decimal
    asset_amount: Decimal


def is_current_natural_month(operation_date: date, *, today: date | None = None) -> bool:
    """True si `operation_date` cae en el mismo año/mes que el día natural `today`."""
    current = today or date.today()
    return (operation_date.year, operation_date.month) == (current.year, current.month)


def executed_at_as_date(fill: dict) -> date | None:
    """Día de ejecución usado para el snapshot; obligatorio en automatizaciones."""
    executed_at = fill.get("executed_at")
    if isinstance(executed_at, datetime):
        return executed_at.date()
    return None


def group_fills_for_current_month_snapshot(
    inserted_fills: list[dict],
    *,
    today: date | None = None,
) -> tuple[dict[tuple[str, int, int], list[SnapshotFill]], int]:
    """Agrupa fills insertados hacia la fila del mes natural actual.

    Devuelve (grupos, fills_omitidos_por_no_ser_mes_actual).
    """
    current = today or date.today()
    target_year, target_month = current.year, current.month
    skipped_not_current = 0
    grouped: dict[tuple[str, int, int], list[SnapshotFill]] = defaultdict(list)

    for fill in inserted_fills:
        if Decimal(str(fill["asset_amount"])) <= 0:
            continue
        execution_day = executed_at_as_date(fill)
        if execution_day is None:
            logger.warning(
                "Snapshot omitido: fill sin executed_at (exchange_trade_id=%s)",
                fill.get("exchange_trade_id"),
            )
            continue
        if not is_current_natural_month(execution_day, today=current):
            skipped_not_current += 1
            logger.info(
                "Snapshot omitido: executed_at %s fuera del mes actual %s-%02d (exchange_trade_id=%s)",
                execution_day.isoformat(),
                target_year,
                target_month,
                fill.get("exchange_trade_id"),
            )
            continue

        grouped[(str(fill["asset_type_id"]), target_year, target_month)].append(
            SnapshotFill(
                asset_type_id=str(fill["asset_type_id"]),
                year=target_year,
                month=target_month,
                executed_at=fill.get("executed_at"),
                invested_amount=Decimal(str(fill["invested_amount"])),
                asset_amount=Decimal(str(fill["asset_amount"])),
            )
        )

    return grouped, skipped_not_current


@dataclass(frozen=True)
class SnapshotApplyResult:
    """Resumen de una pasada de apply_transactions_to_monthly_snapshot."""

    fills_considered: int
    fills_skipped_not_current_month: int
    groups_processed: int


@dataclass(frozen=True)
class SnapshotDecision:
    """Resultado puro de decidir qué hacer con una fila, sin tocar la BD.

    Aislado a propósito para poder testear la regla de `last_update` sin
    levantar Postgres.
    """

    should_update: bool
    new_amount: Decimal
    new_units: Decimal
    new_last_update: datetime | None


def decide_snapshot_update(
    *,
    existing_amount: Decimal,
    existing_units: Decimal,
    existing_last_update: datetime | None,
    fills: list[SnapshotFill],
) -> SnapshotDecision:
    """Aplica la regla de `last_update` a un grupo de fills de un mismo (activo, año, mes).

    `fills` no puede estar vacío. Si `existing_last_update` es `None` se toman
    todos (fila nueva o nunca actualizada). Si no, solo los que su
    `executed_at` sea estrictamente posterior al `last_update` actual.
    """
    if not fills:
        raise ValueError("decide_snapshot_update necesita al menos un fill")

    applicable = [
        f
        for f in fills
        if existing_last_update is None or f.executed_at is None or f.executed_at > existing_last_update
    ]
    if not applicable:
        return SnapshotDecision(
            should_update=False,
            new_amount=existing_amount,
            new_units=existing_units,
            new_last_update=existing_last_update,
        )

    added_amount = sum((f.invested_amount for f in applicable), Decimal("0"))
    added_units = sum((f.asset_amount for f in applicable), Decimal("0"))
    executed_ats = [f.executed_at for f in applicable if f.executed_at is not None]
    latest_executed_at = max(executed_ats) if executed_ats else existing_last_update

    return SnapshotDecision(
        should_update=True,
        new_amount=(existing_amount + added_amount).quantize(_AMOUNT_QUANT),
        new_units=(existing_units + added_units).quantize(_UNITS_QUANT),
        new_last_update=latest_executed_at,
    )


def _apply_sell_fills_to_monthly_snapshot(
    db: Session,
    sell_fills: list[dict],
    *,
    today: date | None = None,
) -> int:
    """Resta unidades vendidas usando PMP de la fila monthly del mes actual (no de txs)."""
    current = today or date.today()
    target_year, target_month = current.year, current.month
    by_asset: dict[str, list[dict]] = defaultdict(list)

    for fill in sell_fills:
        execution_day = executed_at_as_date(fill)
        if execution_day is None:
            logger.warning(
                "Snapshot venta omitido: sin executed_at (exchange_trade_id=%s)",
                fill.get("exchange_trade_id"),
            )
            continue
        if not is_current_natural_month(execution_day, today=current):
            continue
        by_asset[str(fill["asset_type_id"])].append(fill)

    if not by_asset:
        return 0

    ensure_current_month_snapshots(db, today=current)
    groups = 0

    for asset_type_id, fills in by_asset.items():
        q_total = sum(
            (abs(Decimal(str(f["asset_amount"]))) for f in fills),
            Decimal("0"),
        )
        if q_total <= 0:
            continue

        row = _load_row(db, asset_type_id=asset_type_id, year=target_year, month=target_month)
        if row is None:
            logger.warning(
                "Snapshot venta omitido: sin fila monthly %s-%02d para asset_type_id=%s",
                target_year,
                target_month,
                asset_type_id,
            )
            continue

        units = Decimal(str(row.units)) if row.units is not None else Decimal("0")
        amount = Decimal(str(row.amount))
        if units <= 0:
            logger.warning(
                "Snapshot venta omitido: units<=0 en monthly para asset_type_id=%s",
                asset_type_id,
            )
            continue

        pmp = (amount / units).quantize(Decimal("0.0001"))
        executed_ats = [f["executed_at"] for f in fills if f.get("executed_at") is not None]
        latest_executed_at = max(executed_ats) if executed_ats else None

        if row.last_update is not None and latest_executed_at is not None:
            if latest_executed_at <= row.last_update:
                logger.info(
                    "Snapshot venta sin cambios para asset_type_id=%s %s-%02d (last_update=%s)",
                    asset_type_id,
                    target_year,
                    target_month,
                    row.last_update,
                )
                continue

        new_units = (units - q_total).quantize(_UNITS_QUANT)
        if new_units < 0:
            logger.warning(
                "Snapshot venta: units vendidas (%s) > posición (%s) asset_type_id=%s; se capa a 0",
                q_total,
                units,
                asset_type_id,
            )
            new_units = Decimal("0")

        new_amount = (new_units * pmp).quantize(_AMOUNT_QUANT)
        row.units = new_units
        row.amount = new_amount
        if latest_executed_at is not None:
            row.last_update = latest_executed_at

        groups += 1
        logger.info(
            "monthly_asset_investments venta asset_type_id=%s %s-%02d: units %s→%s amount %s→%s (PMP=%s)",
            asset_type_id,
            target_year,
            target_month,
            units,
            new_units,
            amount,
            new_amount,
            pmp,
        )

    return groups


def apply_transactions_to_monthly_snapshot(
    db: Session,
    inserted_fills: list[dict],
    *,
    today: date | None = None,
) -> SnapshotApplyResult:
    """Punto de entrada: compras suman importe; ventas restan unidades vía PMP monthly.

    Se llama tras insertar en `asset_transactions` (y ventas con asset_sales OK).
    """
    empty = SnapshotApplyResult(fills_considered=0, fills_skipped_not_current_month=0, groups_processed=0)
    if not inserted_fills:
        return empty

    current = today or date.today()
    buy_fills = [f for f in inserted_fills if Decimal(str(f["asset_amount"])) > 0]
    sell_fills = [f for f in inserted_fills if Decimal(str(f["asset_amount"])) < 0]

    grouped, skipped_not_current = group_fills_for_current_month_snapshot(
        buy_fills,
        today=current,
    )
    sell_groups = 0
    if sell_fills:
        sell_groups = _apply_sell_fills_to_monthly_snapshot(db, sell_fills, today=current)

    if grouped:
        ensure_current_month_snapshots(db, today=current)
        for (asset_type_id, year, month), fills in grouped.items():
            _apply_group(db, asset_type_id=asset_type_id, year=year, month=month, fills=fills)

    if grouped or sell_groups:
        db.commit()

    return SnapshotApplyResult(
        fills_considered=len(inserted_fills),
        fills_skipped_not_current_month=skipped_not_current,
        groups_processed=len(grouped) + sell_groups,
    )


def _load_row(db: Session, *, asset_type_id: str, year: int, month: int) -> MonthlyAssetInvestment | None:
    return db.scalars(
        select(MonthlyAssetInvestment).where(
            MonthlyAssetInvestment.year == year,
            MonthlyAssetInvestment.month == month,
            MonthlyAssetInvestment.asset_type_id == asset_type_id,
        )
    ).first()


def _apply_group(db: Session, *, asset_type_id: str, year: int, month: int, fills: list[SnapshotFill]) -> None:
    row = _load_row(db, asset_type_id=asset_type_id, year=year, month=month)

    if row is None:
        prev_year, prev_month = _previous_year_month(year, month)
        prev_row = _load_row(db, asset_type_id=asset_type_id, year=prev_year, month=prev_month)
        if prev_row is None:
            logger.warning(
                "monthly_asset_investments sin fila previa para asset_type_id=%s en %s-%02d; "
                "se crea %s-%02d partiendo de 0. Caso extremo: revisar a mano si no es correcto.",
                asset_type_id,
                prev_year,
                prev_month,
                year,
                month,
            )
        base_amount = Decimal(str(prev_row.amount)) if prev_row is not None else Decimal("0")
        base_units = (
            Decimal(str(prev_row.units)) if prev_row is not None and prev_row.units is not None else Decimal("0")
        )

        decision = decide_snapshot_update(
            existing_amount=base_amount,
            existing_units=base_units,
            existing_last_update=None,
            fills=fills,
        )
        db.add(
            MonthlyAssetInvestment(
                year=year,
                month=month,
                asset_type_id=asset_type_id,
                amount=decision.new_amount,
                units=decision.new_units,
                last_update=decision.new_last_update,
            )
        )
        logger.info(
            "monthly_asset_investments creado para asset_type_id=%s %s-%02d: amount=%s units=%s last_update=%s",
            asset_type_id,
            year,
            month,
            decision.new_amount,
            decision.new_units,
            decision.new_last_update,
        )
        return

    existing_amount = Decimal(str(row.amount))
    existing_units = Decimal(str(row.units)) if row.units is not None else Decimal("0")
    decision = decide_snapshot_update(
        existing_amount=existing_amount,
        existing_units=existing_units,
        existing_last_update=row.last_update,
        fills=fills,
    )
    if not decision.should_update:
        logger.info(
            "monthly_asset_investments sin cambios para asset_type_id=%s %s-%02d "
            "(last_update=%s ya cubre las transacciones nuevas; caso extremo aceptado si no debería)",
            asset_type_id,
            year,
            month,
            row.last_update,
        )
        return

    row.amount = decision.new_amount
    row.units = decision.new_units
    row.last_update = decision.new_last_update
    logger.info(
        "monthly_asset_investments actualizado para asset_type_id=%s %s-%02d: amount=%s units=%s last_update=%s",
        asset_type_id,
        year,
        month,
        decision.new_amount,
        decision.new_units,
        decision.new_last_update,
    )


def ensure_current_month_snapshots(db: Session, *, today: date | None = None) -> int:
    """Abre el mes natural actual para todo activo que ya tenga histórico en la tabla.

    Para cada `asset_type_id` con >= 1 fila en `monthly_asset_investments`, si
    no existe fila para (año, mes) actual, la crea copiando `amount`/`units`
    de la última fila anterior existente, avanzando mes a mes si hiciera falta
    rellenar más de uno (p. ej. tras un tiempo parado). `last_update` queda en
    el primer instante del mes creado (`datetime(year, month, 1)`).

    Es idempotente: si ya existe la fila del mes actual, no hace nada para
    ese activo. Devuelve cuántas filas nuevas se crearon en total.
    """
    current = today or date.today()
    target = (current.year, current.month)

    asset_type_ids = db.scalars(select(MonthlyAssetInvestment.asset_type_id).distinct()).all()
    created = 0

    for asset_type_id in asset_type_ids:
        latest = db.scalars(
            select(MonthlyAssetInvestment)
            .where(MonthlyAssetInvestment.asset_type_id == asset_type_id)
            .order_by(MonthlyAssetInvestment.year.desc(), MonthlyAssetInvestment.month.desc())
        ).first()
        if latest is None:
            continue

        year, month = latest.year, latest.month
        amount = Decimal(str(latest.amount))
        units = Decimal(str(latest.units)) if latest.units is not None else None

        while (year, month) < target:
            year, month = _next_year_month(year, month)
            existing = _load_row(db, asset_type_id=str(asset_type_id), year=year, month=month)
            if existing is not None:
                amount = Decimal(str(existing.amount))
                units = Decimal(str(existing.units)) if existing.units is not None else None
                continue

            db.add(
                MonthlyAssetInvestment(
                    year=year,
                    month=month,
                    asset_type_id=asset_type_id,
                    amount=amount,
                    units=units,
                    last_update=datetime(year, month, 1),
                )
            )
            created += 1
            logger.info(
                "monthly_asset_investments abierto para asset_type_id=%s %s-%02d (copiado del cierre anterior)",
                asset_type_id,
                year,
                month,
            )

    if created:
        db.commit()
    return created


def run_ensure_current_month_snapshots() -> int:
    """Abre su propia sesión. Pensado para llamarse desde el scheduler."""
    with SessionLocal() as db:
        return ensure_current_month_snapshots(db)
