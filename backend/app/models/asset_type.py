import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssetType(Base):
    """Catálogo estático de activos concretos (BTC, ETH, BABA, MSCI World...)."""

    __tablename__ = "asset_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[str] = mapped_column(String(30), ForeignKey("investment_categories.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_contribution: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(30), ForeignKey("entities.id"), nullable=True)
    # Proveedor de precio de mercado en vivo para `ticker` ('kucoin' | 'yahoo'). No confundir con
    # `exchange_ticker` (código corto usado solo para casar fills de KuCoin en asset_transactions).
    price_source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    category: Mapped["InvestmentCategory"] = relationship()
    entity: Mapped["Entity | None"] = relationship()
