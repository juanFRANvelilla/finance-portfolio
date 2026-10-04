"""Tareas programadas en segundo plano (APScheduler)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.kucoin_fiat_cash_flows_sync_service import run_scheduled_kucoin_fiat_cash_flows_sync
from app.services.kucoin_sync_service import run_scheduled_kucoin_sync
from app.services.monthly_asset_snapshot import run_ensure_current_month_snapshots
from app.services.monthly_entity_position_snapshot import run_ensure_current_month_entity_positions
from app.services.myinvestor_sync_service import run_scheduled_myinvestor_sync
from app.services.myinvestor_transfers_sync_service import run_scheduled_myinvestor_transfers_sync

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Ciclo único: apertura de mes → KuCoin → MyInvestor (cada 4 h + arranque en background).
PORTFOLIO_SYNC_INTERVAL_HOURS = 4
KUCOIN_SYNC_INTERVAL_HOURS = PORTFOLIO_SYNC_INTERVAL_HOURS
MYINVESTOR_SYNC_INTERVAL_HOURS = PORTFOLIO_SYNC_INTERVAL_HOURS


def _defer_interval_job_first_run(*, hours: int) -> datetime:
    """La primera ejecución periódica la retrasa; el arranque la lanza `main` en background."""
    return datetime.now(timezone.utc) + timedelta(hours=hours)


async def _run_monthly_asset_investments_opening() -> int:
    logger.info("--- Apertura de mes: monthly_asset_investments ---")
    try:
        created = await asyncio.to_thread(run_ensure_current_month_snapshots)
        if created:
            logger.info("monthly_asset_investments: %s fila(s) nueva(s)", created)
        else:
            logger.info("monthly_asset_investments: sin filas nuevas")
        return created
    except Exception:
        logger.exception("Error abriendo mes en monthly_asset_investments")
        raise
    finally:
        logger.info("--- Fin apertura: monthly_asset_investments ---")


async def _run_monthly_entity_positions_opening() -> int:
    logger.info("--- Apertura de mes: monthly_entity_positions ---")
    try:
        created = await asyncio.to_thread(run_ensure_current_month_entity_positions)
        if created:
            logger.info("monthly_entity_positions: %s fila(s) nueva(s)", created)
        else:
            logger.info("monthly_entity_positions: sin filas nuevas")
        return created
    except Exception:
        logger.exception("Error abriendo mes en monthly_entity_positions")
        raise
    finally:
        logger.info("--- Fin apertura: monthly_entity_positions ---")


async def _ensure_current_month_tables_before_sync() -> None:
    """Abre el mes en curso en activos y entidades (una vez por ciclo de importación)."""
    await asyncio.gather(
        _run_monthly_asset_investments_opening(),
        _run_monthly_entity_positions_opening(),
    )


async def _run_kucoin_sync_pipeline() -> None:
    """Fills de trading + fiat EUR → entity_cash_flows (sin apertura de mes)."""
    logger.info("--- Sync KuCoin (operaciones + fiat) ---")
    trades = await asyncio.to_thread(run_scheduled_kucoin_sync)
    if trades.success:
        logger.info(
            "Sync KuCoin operaciones: %s tx insertadas, %s ventas insertadas, "
            "%s duplicados, %s fills (desde %s)",
            trades.inserted,
            trades.sales_inserted,
            trades.skipped_duplicate + trades.sales_skipped_duplicate,
            trades.raw_fills_count,
            trades.start_date.date(),
        )
    else:
        logger.warning("Sync KuCoin operaciones con error: %s", trades.error)

    fiat = await asyncio.to_thread(run_scheduled_kucoin_fiat_cash_flows_sync)
    if fiat.success:
        logger.info(
            "Sync KuCoin fiat EUR: %s insertados, %s duplicados (desde %s)",
            fiat.inserted,
            fiat.skipped_duplicate,
            fiat.start_date.date(),
        )
    else:
        logger.warning("Sync KuCoin fiat EUR con error: %s", fiat.error)
    logger.info("--- Fin sync KuCoin ---")


async def _run_myinvestor_sync_pipeline() -> None:
    """IMAP operaciones + transferencias (sin apertura de mes)."""
    logger.info("--- Sync MyInvestor (operaciones + transferencias) ---")
    trades = await asyncio.to_thread(run_scheduled_myinvestor_sync)
    if trades.success:
        logger.info(
            "Sync MyInvestor operaciones: %s insertados, %s duplicados, %s correos",
            trades.inserted,
            trades.skipped_duplicate,
            trades.raw_emails_count,
        )
    else:
        logger.warning("Sync MyInvestor operaciones con error: %s", trades.error)

    transfers = await asyncio.to_thread(run_scheduled_myinvestor_transfers_sync)
    if transfers.success:
        logger.info(
            "Sync MyInvestor transferencias: %s insertados, %s duplicados, %s correos",
            transfers.inserted,
            transfers.skipped_duplicate,
            transfers.raw_emails_count,
        )
    else:
        logger.warning("Sync MyInvestor transferencias con error: %s", transfers.error)
    logger.info("--- Fin sync MyInvestor ---")


async def _portfolio_sync_cycle_job() -> None:
    """Apertura de mes (activos + entidades) → KuCoin → MyInvestor."""
    logger.info("=== Inicio ciclo portfolio: apertura de mes + importaciones ===")
    try:
        await _ensure_current_month_tables_before_sync()
        await _run_kucoin_sync_pipeline()
        await _run_myinvestor_sync_pipeline()
    except asyncio.CancelledError:
        logger.info("Ciclo portfolio cancelado")
        raise
    except Exception:
        logger.exception("Error inesperado en el ciclo portfolio")
    finally:
        logger.info("=== Fin ciclo portfolio ===")


def start_scheduler() -> AsyncIOScheduler:
    """Arranca el scheduler con un único job periódico de ciclo completo."""
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _portfolio_sync_cycle_job,
        trigger="interval",
        hours=PORTFOLIO_SYNC_INTERVAL_HOURS,
        next_run_time=_defer_interval_job_first_run(hours=PORTFOLIO_SYNC_INTERVAL_HOURS),
        id="portfolio_sync_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.start()
    logger.info(
        "Ciclo portfolio programado: arranque en background; luego cada %s h "
        "(apertura de mes una vez → KuCoin → MyInvestor)",
        PORTFOLIO_SYNC_INTERVAL_HOURS,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    """Detiene el scheduler limpiamente."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler detenido")


def start_portfolio_sync_background() -> asyncio.Task:
    """Primer ciclo completo en background (no bloquea el arranque del API)."""
    logger.info("Primera ejecución del ciclo portfolio en segundo plano...")
    return asyncio.create_task(_portfolio_sync_cycle_job(), name="portfolio-sync-startup")


async def run_startup_monthly_snapshot_rollover() -> None:
    """Solo apertura de mes (p. ej. tests o uso manual). El arranque normal usa el ciclo completo."""
    logger.info("Apertura de mes: monthly_asset_investments + monthly_entity_positions...")
    await _ensure_current_month_tables_before_sync()
