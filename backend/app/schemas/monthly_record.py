from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.entity import EntityRead


class EntityBalanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    balance_amount: float
    entity: EntityRead | None = None


class HybridAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    liquid_amount: float
    monthly_contribution: float
    cumulative_invested: float
    entity: EntityRead | None = None


class EntityBalanceInput(BaseModel):
    entity_id: str
    balance_amount: float = Field(ge=0)


class MonthlyRecordUpsert(BaseModel):
    balances: list[EntityBalanceInput]


class MonthlyRecordDto(BaseModel):
    """DTO con totales persistidos en monthly_records (+ diff y % calculados en backend)."""

    id: UUID
    year: int
    month: int
    created_at: datetime
    balances: list[EntityBalanceRead] = []
    hybrid_accounts: list[HybridAccountRead] = []
    total_liquid: float
    total_invested: float
    total_net_worth: float
    invested_percentage: float
    monthly_diff: float | None = None
    invested_diff: float | None = None


class MonthlyRecordResponse(BaseModel):
    exists: bool
    year: int
    month: int
    record: MonthlyRecordDto | None = None
    previous_net_worth: float | None = None
    previous_total_invested: float | None = None


class TimelinePoint(BaseModel):
    year: int
    month: int
    total_net_worth: float
    total_invested: float
    net_worth_diff: float | None = None
    invested_diff: float | None = None


class TimelineResponse(BaseModel):
    points: list[TimelinePoint] = []


class SimpleBalanceImport(BaseModel):
    entity_id: str
    amount: float = Field(ge=0)


class HybridBalanceImport(BaseModel):
    entity_id: str
    liquid_amount: float = Field(ge=0)
    invested_amount: float = Field(ge=0)


class ExpectedTotalsImport(BaseModel):
    total_liquid: float = Field(ge=0)
    total_invested: float = Field(ge=0)
    total_net_worth: float = Field(ge=0)


class ImportPayload(BaseModel):
    simple_balances: list[SimpleBalanceImport] = Field(default_factory=list)
    hybrid_balances: list[HybridBalanceImport] = Field(default_factory=list)
    expected_totals: ExpectedTotalsImport
