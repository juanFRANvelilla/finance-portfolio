import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssetTransaction(Base):
    """Operaciones de exchange (compras + ventas KuCoin). Ventas: importes/unidades negativos."""

    __tablename__ = "asset_transactions"
    __table_args__ = (UniqueConstraint("exchange_trade_id", name="uq_asset_transactions_exchange_trade_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False
    )
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    """Día de negocio: se usa para cortes de mes, ledger, etc. No cambia de significado."""
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """Fecha y hora exacta de ejecución (la que trae el exchange/correo).
    Es lo que se compara contra monthly_asset_investments.last_update."""
    invested_amount: Mapped[float | None] = mapped_column(Numeric(16, 8), nullable=True)
    """Importe en divisa del activo. Obligatorio en compras; NULL en ventas (solo unidades negativas)."""
    asset_amount: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    execution_price: Mapped[float | None] = mapped_column(Numeric(16, 8), nullable=True)
    fee_amount: Mapped[float | None] = mapped_column(Numeric(16, 8), nullable=True)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    asset_type: Mapped["AssetType"] = relationship()
