import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyEntityPosition(Base):
    __tablename__ = "monthly_entity_positions"
    __table_args__ = (
        UniqueConstraint("year", "month", "entity_id", name="uq_monthly_entity_positions_year_month_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(30), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    liquid_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    cumulative_invested: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entity: Mapped["Entity"] = relationship(back_populates="monthly_positions")
