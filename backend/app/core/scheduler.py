"""Tareas programadas en segundo plano (APScheduler)."""

from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.kucoin_fiat_cash_flows_sync_service import run_scheduled_kucoin_fiat_cash_flows_sync
from app.services.kucoin_sync_service import run_scheduled_kucoin_sync
from app.services.monthly_asset_snapshot import run_ensure_current_month_snapshots
from app.services.myinvestor_sync_service import run_scheduled_myinvestor_sync
from app.services.myinvestor_transfers_sync_service import run_scheduled_myinvestor_transfers_sync

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Sincronización periódica con KuCoin (producción: cada 4 horas).
KUCOIN_SYNC_INTERVAL_HOURS = 4
# Confirmaciones MyInvestor por IMAP. Independiente del job de KuCoin.
MYINVESTOR_SYNC_INTERVAL_HOURS = 4
# Apertura del mes natural en monthly_asset_investments (cron + al arrancar el pod).
MONTHLY_SNAPSHOT_ROLLOVER_CRON_HOUR = 2
MONTHLY_SNAPSHOT_ROLLOVER_CRON_MINUTE = 0
MONTHLY_SNAPSHOT_ROLLOVER_TIMEZONE = ZoneInfo("Europe/Madrid")


async def _kucoin_sync_job() -> None:
    """Wrapper async: fills de trading + fiat EUR → entity_cash_flows (hilos)."""
    logger.info("--- Inicio tarea programada: sync KuCoin ---")
    try:
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
    except asyncio.CancelledError:
        logger.info("Sync KuCoin cancelada")
        raise
    except Exception:
        logger.exception("Error inesperado en la tarea programada de KuCoin")
    finally:
        logger.info("--- Fin tarea programada: sync KuCoin ---")


async def _myinvestor_sync_job() -> None:
    """Wrapper async: IMAP bloqueante en hilo (operaciones + transferencias)."""
    logger.info("--- Inicio tarea programada: sync MyInvestor ---")
    try:
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
    except asyncio.CancelledError:
        logger.info("Sync MyInvestor cancelada")
        raise
    except Exception:
        logger.exception("Error inesperado en la tarea programada de MyInvestor")
    finally:
        logger.info("--- Fin tarea programada: sync MyInvestor ---")


async def _monthly_snapshot_rollover_job() -> None:
    """Wrapper async: abre el mes natural actual en monthly_asset_investments si falta.

    Independiente de KuCoin/MyInvestor: no trae transacciones nuevas, solo se
    asegura de que el mes en curso tenga fila (copiando el cierre anterior).
    """
    logger.info("--- Inicio tarea programada: apertura de mes en monthly_asset_investments ---")
    try:
        created = await asyncio.to_thread(run_ensure_current_month_snapshots)
        if created:
            logger.info("Apertura de mes: %s fila(s) nueva(s) creada(s)", created)
        else:
            logger.info("Apertura de mes: no hacía falta crear filas nuevas")
    except asyncio.CancelledError:
        logger.info("Apertura de mes cancelada")
        raise
    except Exception:
        logger.exception("Error inesperado abriendo el mes en monthly_asset_investments")
    finally:
        logger.info("--- Fin tarea programada: apertura de mes ---")


def start_scheduler() -> AsyncIOScheduler:
    """Arranca el scheduler y registra las tareas periódicas."""
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _kucoin_sync_job,
        trigger="interval",
        hours=KUCOIN_SYNC_INTERVAL_HOURS,
        id="kucoin_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _myinvestor_sync_job,
        trigger="interval",
        hours=MYINVESTOR_SYNC_INTERVAL_HOURS,
        id="myinvestor_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _monthly_snapshot_rollover_job,
        trigger=CronTrigger(
            hour=MONTHLY_SNAPSHOT_ROLLOVER_CRON_HOUR,
            minute=MONTHLY_SNAPSHOT_ROLLOVER_CRON_MINUTE,
            timezone=MONTHLY_SNAPSHOT_ROLLOVER_TIMEZONE,
        ),
        id="monthly_snapshot_rollover",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.start()
    logger.info(
        "Tarea programada KuCoin activa (operaciones + fiat EUR): "
        "al arrancar y cada %s horas",
        KUCOIN_SYNC_INTERVAL_HOURS,
    )
    logger.info(
        "Tarea programada MyInvestor activa (operaciones + transferencias): "
        "al arrancar y cada %s horas",
        MYINVESTOR_SYNC_INTERVAL_HOURS,
    )
    logger.info(
        "Tarea programada de apertura de mes activa: al arrancar y cada noche a las %02d:%02d (%s)",
        MONTHLY_SNAPSHOT_ROLLOVER_CRON_HOUR,
        MONTHLY_SNAPSHOT_ROLLOVER_CRON_MINUTE,
        MONTHLY_SNAPSHOT_ROLLOVER_TIMEZONE.key,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    """Detiene el scheduler limpiamente."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler detenido")


def start_kucoin_sync_background() -> asyncio.Task:
    """Lanza la sync de arranque en segundo plano para no retrasar el API."""
    logger.info("Primera ejecución de sync KuCoin en segundo plano...")
    return asyncio.create_task(_kucoin_sync_job(), name="kucoin-sync-startup")


def start_myinvestor_sync_background() -> asyncio.Task:
    """Lanza la sync IMAP de arranque en segundo plano para no retrasar el API."""
    logger.info("Primera ejecución de sync MyInvestor en segundo plano...")
    return asyncio.create_task(_myinvestor_sync_job(), name="myinvestor-sync-startup")


def start_monthly_snapshot_rollover_background() -> asyncio.Task:
    """Lanza la apertura de mes de arranque en segundo plano para no retrasar el API."""
    logger.info("Primera comprobación de apertura de mes en segundo plano...")
    return asyncio.create_task(_monthly_snapshot_rollover_job(), name="monthly-snapshot-rollover-startup")
