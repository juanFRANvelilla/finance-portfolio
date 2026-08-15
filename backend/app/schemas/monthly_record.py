from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.entity import EntityRead


class EntityBalanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    balance_amount: float
    entity: EntityRead | None = None


class EntityBalanceInput(BaseModel):
    """Balance introducido por el usuario para una entidad concreta en un mes."""

    entity_id: str
    balance_amount: float = Field(ge=0)


class MonthlyRecordUpsert(BaseModel):
    """Payload para crear/actualizar los balances de un mes."""

    balances: list[EntityBalanceInput]


class MonthlyRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    month: int
    total_liquid: float
    total_invested: float
    total_net_worth: float
    monthly_diff: float | None
    invested_percentage: float
    created_at: datetime
    balances: list[EntityBalanceRead] = []


class MonthlyRecordResponse(BaseModel):
    """Respuesta enriquecida del GET, incluye si existe registro y el diff previo."""

    exists: bool
    year: int
    month: int
    record: MonthlyRecordRead | None = None
    previous_net_worth: float | None = None


class ImportJsonPayload(BaseModel):
    """Placeholder de payload para la ingesta masiva de meses historicos."""

    months: list[dict] = Field(default_factory=list)


class ImportJsonResponse(BaseModel):
    status: str
    imported_count: int
    detail: str
