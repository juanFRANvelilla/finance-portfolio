from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import check_db_connection
from app.core.scheduler import start_kucoin_sync_background, shutdown_scheduler, start_scheduler
from app.routers import asset_sales, contributions, entities, investments, ledger, market_prices, records
from app.routers.asset_sales import v1_router as asset_sales_v1_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    force=True,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        check_db_connection()
        logger.info("Conexion a PostgreSQL OK")
    except Exception as exc:
        logger.warning("PostgreSQL no disponible al arrancar: %s", exc)

    start_scheduler()
    app.state.kucoin_sync_task = start_kucoin_sync_background()

    yield

    task = getattr(app.state, "kucoin_sync_task", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    shutdown_scheduler()


app = FastAPI(
    title="Finance Portfolio API",
    description="API REST para el seguimiento de patrimonio personal (liquido vs invertido).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entities.router)
app.include_router(records.router)
app.include_router(contributions.router)
app.include_router(investments.router)
app.include_router(asset_sales.router)
app.include_router(asset_sales_v1_router)
app.include_router(ledger.router)
app.include_router(market_prices.router)


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
