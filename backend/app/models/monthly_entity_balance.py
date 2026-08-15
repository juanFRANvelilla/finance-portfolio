import uuid

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyEntityBalance(Base):
    __tablename__ = "monthly_entity_balances"
    __table_args__ = (UniqueConstraint("record_id", "entity_id", name="uq_balance_record_entity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monthly_records.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(30), ForeignKey("entities.id"), nullable=False)
    balance_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    record: Mapped["MonthlyRecord"] = relationship(back_populates="balances")
    entity: Mapped["Entity"] = relationship(back_populates="balances")
