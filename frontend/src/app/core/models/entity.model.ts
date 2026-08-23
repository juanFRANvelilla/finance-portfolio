export type EntityType = 'LIQUID' | 'INVESTED' | 'HYBRID';

export interface Entity {
  id: string;
  name: string;
  entity_type: EntityType;
  is_active: boolean;
  default_category_id: string | null;
}
