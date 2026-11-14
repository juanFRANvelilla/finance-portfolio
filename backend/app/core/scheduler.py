"""Tareas programadas en segundo plano (APScheduler)."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
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
# KuCoin + MyInvestor (operaciones e IMAP) en un solo hilo, fuera del event loop.
_import_executor: ThreadPoolExecutor | None = None
_portfolio_sync_in_progress = False
_portfolio_sync_gate = threading.Lock()

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


def _get_import_executor() -> ThreadPoolExecutor:
    global _import_executor
    if _import_executor is None:
        _import_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="portfolio-import",
        )
    return _import_executor


def _run_kucoin_sync_pipeline_blocking() -> None:
    """Fills de trading + fiat EUR → entity_cash_flows (hilo de importación)."""
    logger.info("--- Sync KuCoin (operaciones + fiat) ---")
    trades = run_scheduled_kucoin_sync()
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

    fiat = run_scheduled_kucoin_fiat_cash_flows_sync()
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


def _run_myinvestor_sync_pipeline_blocking() -> None:
    """IMAP operaciones + transferencias (hilo de importación)."""
    logger.info("--- Sync MyInvestor (operaciones + transferencias) ---")
    trades = run_scheduled_myinvestor_sync()
    if trades.success:
        logger.info(
            "Sync MyInvestor operaciones: %s insertados, %s ventas asset_sales, %s duplicados, %s correos",
            trades.inserted,
            trades.sales_inserted,
            trades.skipped_duplicate,
            trades.raw_emails_count,
        )
    else:
        logger.warning("Sync MyInvestor operaciones con error: %s", trades.error)

    transfers = run_scheduled_myinvestor_transfers_sync()
    if transfers.success:
        logger.info(
            "Sync MyInvestor transferencias: %s insertados, %s duplicados, "
            "%s líquido ajustado, %s correos",
            transfers.inserted,
            transfers.skipped_duplicate,
            transfers.liquid_adjusted,
            transfers.raw_emails_count,
        )
    else:
        logger.warning("Sync MyInvestor transferencias con error: %s", transfers.error)
    logger.info("--- Fin sync MyInvestor ---")


def _run_portfolio_imports_blocking() -> None:
    """KuCoin y MyInvestor en serie en el único hilo de importación."""
    _run_kucoin_sync_pipeline_blocking()
    _run_myinvestor_sync_pipeline_blocking()


async def _run_portfolio_imports_in_worker() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_get_import_executor(), _run_portfolio_imports_blocking)


def portfolio_sync_in_progress() -> bool:
    return _portfolio_sync_in_progress


def schedule_portfolio_sync_cycle() -> bool:
    """Lanza el ciclo en background. Devuelve False si ya hay uno en curso.

    Debe llamarse desde un endpoint/handler async (con event loop activo).
    """
    with _portfolio_sync_gate:
        if _portfolio_sync_in_progress:
            return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        raise RuntimeError(
            "schedule_portfolio_sync_cycle requiere un event loop asyncio activo"
        ) from exc
    loop.create_task(_portfolio_sync_cycle_job(), name="portfolio-sync-manual")
    return True


async def _portfolio_sync_cycle_job() -> None:
    """Apertura de mes (activos + entidades) → KuCoin → MyInvestor."""
    global _portfolio_sync_in_progress
    with _portfolio_sync_gate:
        if _portfolio_sync_in_progress:
            logger.info("Ciclo portfolio omitido: ya hay uno en ejecución")
            return
        _portfolio_sync_in_progress = True
    logger.info("=== Inicio ciclo portfolio: apertura de mes + importaciones ===")
    try:
        await _ensure_current_month_tables_before_sync()
        await _run_portfolio_imports_in_worker()
    except asyncio.CancelledError:
        logger.info("Ciclo portfolio cancelado")
        raise
    except Exception:
        logger.exception("Error inesperado en el ciclo portfolio")
    finally:
        with _portfolio_sync_gate:
            _portfolio_sync_in_progress = False
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
    global _scheduler, _import_executor
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler detenido")
    if _import_executor is not None:
        _import_executor.shutdown(wait=False, cancel_futures=True)
        _import_executor = None
        logger.info("Hilo de importación portfolio detenido")


def start_portfolio_sync_background() -> asyncio.Task:
    """Primer ciclo completo en background (no bloquea el arranque del API)."""
    logger.info("Primera ejecución del ciclo portfolio en segundo plano...")
    return asyncio.create_task(_portfolio_sync_cycle_job(), name="portfolio-sync-startup")


async def run_startup_monthly_snapshot_rollover() -> None:
    """Solo apertura de mes (p. ej. tests o uso manual). El arranque normal usa el ciclo completo."""
    logger.info("Apertura de mes: monthly_asset_investments + monthly_entity_positions...")
    await _ensure_current_month_tables_before_sync()
