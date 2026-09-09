"""Tareas programadas en segundo plano (APScheduler)."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.kucoin_sync_service import run_scheduled_kucoin_sync

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Sincronización periódica con KuCoin (producción: cada 4 horas).
KUCOIN_SYNC_INTERVAL_HOURS = 4


async def _kucoin_sync_job() -> None:
    """Wrapper async: ejecuta la sync bloqueante en un hilo para no bloquear el event loop."""
    logger.info("--- Inicio tarea programada: sync KuCoin ---")
    try:
        result = await asyncio.to_thread(run_scheduled_kucoin_sync)
        if result.success:
            logger.info(
                "Sync KuCoin completada: %s insertados, %s duplicados omitidos, "
                "%s fills brutos (desde %s)",
                result.inserted,
                result.skipped_duplicate,
                result.raw_fills_count,
                result.start_date.date(),
            )
        else:
            logger.warning("Sync KuCoin terminó con error: %s", result.error)
    except Exception:
        logger.exception("Error inesperado en la tarea programada de KuCoin")
    finally:
        logger.info("--- Fin tarea programada: sync KuCoin ---")


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

    _scheduler.start()
    logger.info(
        "Tarea programada KuCoin activa: se ejecutará al arrancar y luego cada %s horas",
        KUCOIN_SYNC_INTERVAL_HOURS,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    """Detiene el scheduler limpiamente."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler detenido (tarea KuCoin cancelada)")


async def run_kucoin_sync_on_startup() -> None:
    """Ejecuta una sincronización inmediata al arrancar el servidor."""
    logger.info("Primera ejecución de sync KuCoin al iniciar el backend...")
    await _kucoin_sync_job()
