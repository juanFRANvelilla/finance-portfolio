import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssetTransaction(Base):
    """Operaciones de compra registradas en exchange (p. ej. fills de KuCoin)."""

    __tablename__ = "asset_transactions"
    __table_args__ = (UniqueConstraint("exchange_trade_id", name="uq_asset_transactions_exchange_trade_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False
    )
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invested_amount: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    """Importe invertido en EUR."""
    asset_amount: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    execution_price: Mapped[float | None] = mapped_column(Numeric(16, 8), nullable=True)
    fee_amount: Mapped[float | None] = mapped_column(Numeric(16, 8), nullable=True)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    asset_type: Mapped["AssetType"] = relationship()
