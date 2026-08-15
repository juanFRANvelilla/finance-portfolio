from pydantic import BaseModel, ConfigDict

from app.models.entity import EntityType


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    entity_type: EntityType
    is_active: bool
