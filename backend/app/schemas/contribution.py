from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_id: str
    contribution_date: date
    amount: float
    notes: str | None = None


class ContributionCreate(BaseModel):
    contribution_date: date
    amount: float = Field(description="Positivo = aportación, negativo = retirada")
    notes: str | None = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def amount_not_zero(cls, value: float) -> float:
        if value == 0:
            raise ValueError("El importe no puede ser cero")
        return value


class EntityContributionsResponse(BaseModel):
    entity_id: str
    year: int
    month: int
    contributions: list[ContributionRead]
    previous_static_total: float
    contributions_total: float
    projected_total: float
    """previous_static_total + contributions_total (antes de restar líquido)."""
    cumulative_invested_preview: float
    """projected_total − liquid_amount enviado como query param (0 por defecto)."""
