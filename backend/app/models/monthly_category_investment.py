import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyCategoryInvestment(Base):
    """Total invertido (en EUR) por categoría de inversión, mes a mes.

    Desacoplada de monthly_records: se referencia directamente por (year, month)
    para poder registrar datos de inversión en cualquier mes, tenga o no
    balances de entidades guardados en el panel principal.
    """

    __tablename__ = "monthly_category_investments"
    __table_args__ = (
        UniqueConstraint("year", "month", "category_id", name="uq_category_investment_year_month_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[str] = mapped_column(String(30), ForeignKey("investment_categories.id"), nullable=False)
    amount_eur: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    category: Mapped["InvestmentCategory"] = relationship()
