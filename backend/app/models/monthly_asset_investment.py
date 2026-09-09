import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyAssetInvestment(Base):
    """Reparto atómico por activo concreto, mes a mes.

    Desacoplada de monthly_records: se referencia directamente por (year, month).
    `amount` se guarda en la divisa definida en asset_types (EUR o USD).
    `units` (nº de títulos/participaciones) es opcional para cualquier activo.
    La conversión a EUR se calcula al vuelo, nunca se persiste aquí.
    """

    __tablename__ = "monthly_asset_investments"
    __table_args__ = (
        UniqueConstraint("year", "month", "asset_type_id", name="uq_asset_investment_year_month_asset"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    units: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)

    asset_type: Mapped["AssetType"] = relationship()
