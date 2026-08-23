from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import check_db_connection
from app.routers import entities, investments, records

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        check_db_connection()
        logger.info("Conexion a PostgreSQL OK")
    except Exception as exc:
        logger.warning("PostgreSQL no disponible al arrancar: %s", exc)
    yield


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
app.include_router(investments.router)


@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
