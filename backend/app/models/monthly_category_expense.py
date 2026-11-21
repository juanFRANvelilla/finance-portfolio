import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyCategoryExpense(Base):
    """Snapshot mensual de gastos agrupados por categoría."""

    __tablename__ = "monthly_category_expenses"
    __table_args__ = (
        UniqueConstraint("year", "month", "category", "source_type", name="uq_monthly_category_expenses_year_month_cat_src"),
        CheckConstraint("month >= 1 AND month <= 12", name="monthly_category_expenses_month_check"),
        CheckConstraint("year >= 2000", name="monthly_category_expenses_year_check"),
        CheckConstraint("amount >= 0", name="monthly_category_expenses_amount_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ACCOUNT")
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["MonthlyCategoryExpenseItem"]] = relationship(
        "MonthlyCategoryExpenseItem",
        back_populates="expense",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class MonthlyCategoryExpenseItem(Base):
    """Detalle de transacciones agrupadas por concepto para una categoría de gasto mensual."""

    __tablename__ = "monthly_category_expense_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monthly_category_expenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    concept: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    expense: Mapped["MonthlyCategoryExpense"] = relationship(
        "MonthlyCategoryExpense",
        back_populates="items",
    )
