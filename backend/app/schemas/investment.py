from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_CURRENCIES = ("EUR", "USD")
ALLOWED_PRICE_SOURCES = ("kucoin", "yahoo")


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
    entity_id: str | None = None
    price_source: str | None = None


class AssetTypeCreate(BaseModel):
    category_id: str
    name: str = Field(min_length=1, max_length=50)
    ticker: str | None = None
    currency: str = "EUR"
    entity_id: str | None = None
    price_source: str | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value not in ALLOWED_CURRENCIES:
            raise ValueError(f"La divisa debe ser una de {ALLOWED_CURRENCIES}")
        return value

    @field_validator("price_source")
    @classmethod
    def validate_price_source(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_PRICE_SOURCES:
            raise ValueError(f"price_source debe ser uno de {ALLOWED_PRICE_SOURCES}")
        return value


class AssetTypeUpdate(BaseModel):
    ticker: str | None = None
    currency: str | None = None
    entity_id: str | None = None
    price_source: str | None = None
    display_order: int | None = Field(default=None, ge=1, le=9999)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_CURRENCIES:
            raise ValueError(f"La divisa debe ser una de {ALLOWED_CURRENCIES}")
        return value

    @field_validator("price_source")
    @classmethod
    def validate_price_source(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_PRICE_SOURCES:
            raise ValueError(f"price_source debe ser uno de {ALLOWED_PRICE_SOURCES}")
        return value


class AssetDisplayOrderItem(BaseModel):
    asset_type_id: UUID
    display_order: int = Field(ge=1, le=9999)


class CategoryAssetDisplayOrderUpdate(BaseModel):
    items: list[AssetDisplayOrderItem] = Field(min_length=1)


class LinkedInvestedTotalResponse(BaseModel):
    entity_id: str
    year: int
    month: int
    total_eur: float
    asset_count: int


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
    editable: bool = True
    saved_this_month: bool = False


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
    category_amount_eur: float | None = Field(
        default=None,
        ge=0,
        description="Total declarado de la categoría en EUR. Debe ser >= suma de activos; el excedente es «Otros».",
    )


class AssetInvestmentDetail(BaseModel):
    asset_type_id: UUID
    name: str
    ticker: str | None = None
    display_order: int
    currency: str
    entity_id: str | None = None
    entity_name: str | None = None
    amount: float
    """Importe en la divisa nativa del activo (EUR o USD según asset_types)."""
    amount_eur: float
    """Equivalente en EUR calculado al vuelo; no se persiste en BD."""
    units: float | None = None
    has_transactions: bool = False
    """True si el activo tiene operaciones en asset_transactions hasta fin del mes consultado."""
    has_sale_this_month: bool = False
    """True si hay al menos una venta en asset_sales para este activo y mes."""


class CategoryDetailResponse(BaseModel):
    year: int
    month: int
    category_id: str
    category_name: str
    is_computed: bool
    """True para Acciones: category_amount_eur es la suma de sus activos, no un valor manual."""
    category_amount_eur: float
    fx_usd_to_eur: float | None = None
    """Tipo de cambio USD→EUR usado para convertir activos de este mes (informativo)."""
    assets: list[AssetInvestmentDetail]
    allocated_amount_eur: float
    others_amount_eur: float
