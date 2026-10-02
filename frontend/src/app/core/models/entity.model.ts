export type EntityType = 'LIQUID' | 'HYBRID';

export interface Entity {
  id: string;
  name: string;
  entity_type: EntityType;
  is_active: boolean;
}
