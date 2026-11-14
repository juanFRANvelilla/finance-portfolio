from pydantic import BaseModel, Field


class PortfolioSyncStatusResponse(BaseModel):
    running: bool


class PortfolioSyncStartResponse(BaseModel):
    status: str = Field(examples=["started"])