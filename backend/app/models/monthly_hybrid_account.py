import uuid

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyHybridAccount(Base):
    __tablename__ = "monthly_hybrid_accounts"
    __table_args__ = (UniqueConstraint("record_id", "entity_id", name="uq_hybrid_record_entity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monthly_records.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(30), ForeignKey("entities.id"), nullable=False)
    liquid_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    monthly_contribution: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    cumulative_invested: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    record: Mapped["MonthlyRecord"] = relationship(back_populates="hybrid_accounts")
    entity: Mapped["Entity"] = relationship(back_populates="hybrid_accounts")
