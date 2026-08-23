import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EntityType(str, enum.Enum):
    LIQUID = "LIQUID"
    INVESTED = "INVESTED"
    HYBRID = "HYBRID"


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type", native_enum=False, validate_strings=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_category_id: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("investment_categories.id"), nullable=True
    )

    balances: Mapped[list["MonthlyEntityBalance"]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
    )
    hybrid_accounts: Mapped[list["MonthlyHybridAccount"]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
    )
