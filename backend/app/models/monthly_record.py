from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyRecord(Base):
    __tablename__ = "monthly_records"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_monthly_records_year_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    total_liquid: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    total_invested: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    total_net_worth: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    monthly_diff: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    invested_percentage: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    balances: Mapped[list["MonthlyEntityBalance"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
    )
