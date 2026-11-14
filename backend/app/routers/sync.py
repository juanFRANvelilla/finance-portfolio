from fastapi import APIRouter, HTTPException, status

from app.core.scheduler import portfolio_sync_in_progress, schedule_portfolio_sync_cycle
from app.schemas.sync import PortfolioSyncStartResponse, PortfolioSyncStatusResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/transactions/status", response_model=PortfolioSyncStatusResponse)
def get_transactions_sync_status() -> PortfolioSyncStatusResponse:
    return PortfolioSyncStatusResponse(running=portfolio_sync_in_progress())


@router.post(
    "/transactions",
    response_model=PortfolioSyncStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_transactions_sync() -> PortfolioSyncStartResponse:
    if not schedule_portfolio_sync_cycle():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una sincronización de transacciones en curso",
        )
    return PortfolioSyncStartResponse(status="started")