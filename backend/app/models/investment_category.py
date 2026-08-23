from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InvestmentCategory(Base):
    """Catálogo estático de categorías de inversión (crypto, fondos, acciones)."""

    __tablename__ = "investment_categories"

    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
