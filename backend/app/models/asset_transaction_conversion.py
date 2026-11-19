import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssetTransactionConversion(Base):
    """Detalle de conversión de divisa (p. ej. USDT -> EUR) para una transacción."""

    __tablename__ = "asset_transaction_conversions"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_transactions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    quote_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    original_invested_amount: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    original_execution_price: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    fx_rate: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    bridge_exchange_trade_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    transaction: Mapped["AssetTransaction"] = relationship(back_populates="conversion")
