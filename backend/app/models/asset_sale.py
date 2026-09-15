import uuid
from datetime import date, datetime

from sqlalchemy import Computed, Date, ForeignKey, Numeric, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssetSale(Base):
    """Venta parcial o total de un activo registrada en un mes concreto."""

    __tablename__ = "asset_sales"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset_types.id", ondelete="RESTRICT"), nullable=False
    )
    units: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    sale_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sale_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    avg_buy_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    sale_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    profit: Mapped[float] = mapped_column(
        Numeric(18, 4),
        Computed("(((sale_price * units) - fee) - (units * avg_buy_price))", persisted=True),
        nullable=False,
    )
    profit_percentage: Mapped[float] = mapped_column(
        Numeric(8, 4),
        Computed(
            "(CASE WHEN avg_buy_price > 0 AND units > 0 THEN ((((sale_price * units) - fee) - (units * avg_buy_price)) / (units * avg_buy_price)) * 100 ELSE 0 END)",
            persisted=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    asset_type: Mapped["AssetType"] = relationship()
