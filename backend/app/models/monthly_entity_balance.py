from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyEntityBalance(Base):
    __tablename__ = "monthly_entity_balances"
    __table_args__ = (
        UniqueConstraint("record_id", "entity_id", name="uq_monthly_entity_balances_record_entity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monthly_records.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String, ForeignKey("entities.id"), nullable=False)
    balance_amount: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)

    record: Mapped["MonthlyRecord"] = relationship(back_populates="balances")
    entity: Mapped["Entity"] = relationship(back_populates="balances")
