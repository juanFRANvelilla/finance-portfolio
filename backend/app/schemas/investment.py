from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_CURRENCIES = ("EUR", "USD")


class InvestmentCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    color: str | None = None
    display_order: int


class AssetTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: str
    name: str
    ticker: str | None = None
    currency: str
    is_active: bool
    display_order: int


class AssetTypeCreate(BaseModel):
    category_id: str
    name: str = Field(min_length=1, max_length=50)
    ticker: str | None = None
    currency: str = "EUR"

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value not in ALLOWED_CURRENCIES:
            raise ValueError(f"La divisa debe ser una de {ALLOWED_CURRENCIES}")
        return value


class CategoryInvestmentInput(BaseModel):
    category_id: str
    amount_eur: float = Field(ge=0)


class CategoryInvestmentsUpsert(BaseModel):
    categories: list[CategoryInvestmentInput]


class CategoryOverview(BaseModel):
    category_id: str
    name: str
    color: str | None = None
    amount_eur: float
    percentage: float
    previous_amount_eur: float | None = None
    entity_amount_eur: float = 0.0
    entity_names: list[str] = Field(default_factory=list)
    editable: bool = True
    """False para categorías cuyo total se calcula solo a partir de sus activos (Acciones)."""
    saved_this_month: bool = False
    """True si ya hay un valor manual guardado para este mes concreto (solo aplica a editables)."""


class InvestmentOverviewResponse(BaseModel):
    year: int
    month: int
    total_invested: float
    """Suma de todas las categorías del detalle de inversión (puede diferir del panel principal)."""
    has_month_record: bool
    """Indica si el mes tiene balances guardados en el panel principal (monthly_records)."""
    categories: list[CategoryOverview]
    previous_year: int
    previous_month: int


class AssetInvestmentInput(BaseModel):
    asset_type_id: UUID
    amount: float = Field(ge=0)
    units: float | None = Field(default=None, ge=0)


class AssetInvestmentsUpsert(BaseModel):
    assets: list[AssetInvestmentInput]


class AssetInvestmentDetail(BaseModel):
    asset_type_id: UUID
    name: str
    ticker: str | None = None
    currency: str
    amount: float
    """Importe en la divisa nativa del activo (EUR o USD según asset_types)."""
    amount_eur: float
    """Equivalente en EUR calculado al vuelo; no se persiste en BD."""
    units: float | None = None
    previous_amount: float | None = None
    previous_units: float | None = None


class CategoryDetailResponse(BaseModel):
    year: int
    month: int
    category_id: str
    category_name: str
    is_computed: bool
    """True para Acciones: category_amount_eur es la suma de sus activos, no un valor manual."""
    has_units: bool
    """True solo para Acciones: sus activos llevan además nº de títulos (units)."""
    category_amount_eur: float
    fx_usd_to_eur: float | None = None
    """Tipo de cambio USD→EUR usado para convertir activos de este mes (informativo)."""
    assets: list[AssetInvestmentDetail]
    allocated_amount_eur: float
    others_amount_eur: float
