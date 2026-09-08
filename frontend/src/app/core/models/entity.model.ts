export type EntityType = 'LIQUID' | 'INVESTED' | 'HYBRID';

export interface Entity {
  id: string;
  name: string;
  entity_type: EntityType;
  is_active: boolean;
  /** Solo HYBRID: true = gestión por aportaciones + preview calculado en UI. */
  uses_contribution_ledger: boolean;
}
