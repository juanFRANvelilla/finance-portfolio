import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyRecord(Base):
    __tablename__ = "monthly_records"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_record_year_month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    balances: Mapped[list["MonthlyEntityBalance"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
    )
    hybrid_accounts: Mapped[list["MonthlyHybridAccount"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
    )
