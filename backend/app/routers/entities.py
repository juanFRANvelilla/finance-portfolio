from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entity import Entity
from app.schemas.entity import EntityRead

router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("", response_model=list[EntityRead])
def list_active_entities(db: Session = Depends(get_db)) -> list[Entity]:
    """Devuelve el listado de entidades activas."""
    stmt = select(Entity).where(Entity.is_active.is_(True)).order_by(Entity.entity_type, Entity.name)
    return list(db.scalars(stmt).all())
