import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EntityCashFlow(Base):
    """Movimientos de caja por entidad (aportaciones / retiradas, importe ±)."""

    __tablename__ = "entity_cash_flows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[str | None] = mapped_column(String(30), ForeignKey("entities.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    flow_date: Mapped[date | None] = mapped_column("deposit_date", Date, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        server_default=func.now(),
    )

    entity: Mapped["Entity | None"] = relationship()
