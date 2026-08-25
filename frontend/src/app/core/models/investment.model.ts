export interface InvestmentCategory {
  id: string;
  name: string;
  color: string | null;
  display_order: number;
}

export interface AssetType {
  id: string;
  category_id: string;
  name: string;
  ticker: string | null;
  currency: string;
  is_active: boolean;
  display_order: number;
}

export interface AssetTypeCreate {
  category_id: string;
  name: string;
  ticker?: string | null;
  currency: string;
}

export interface CategoryInvestmentInput {
  category_id: string;
  amount_eur: number;
}

export interface CategoryInvestmentsUpsert {
  categories: CategoryInvestmentInput[];
}

export interface CategoryOverview {
  category_id: string;
  name: string;
  color: string | null;
  amount_eur: number;
  percentage: number;
  previous_amount_eur: number | null;
  entity_amount_eur: number;
  entity_names: string[];
  /** false para categorías cuyo total se calcula solo a partir de sus activos (Acciones). */
  editable: boolean;
  /** true si ya hay un valor manual guardado para este mes concreto (solo aplica a editables). */
  saved_this_month: boolean;
}

export interface InvestmentOverviewResponse {
  year: number;
  month: number;
  total_invested: number;
  /** Indica si el mes tiene balances guardados en el panel principal. */
  has_month_record: boolean;
  categories: CategoryOverview[];
  previous_year: number;
  previous_month: number;
}

export interface AssetInvestmentInput {
  asset_type_id: string;
  amount: number;
  units?: number | null;
}

export interface AssetInvestmentsUpsert {
  assets: AssetInvestmentInput[];
}

export interface AssetInvestmentDetail {
  asset_type_id: string;
  name: string;
  ticker: string | null;
  currency: string;
  /** Importe en la divisa nativa del activo (EUR o USD según asset_types). */
  amount: number;
  /** Equivalente en EUR calculado al vuelo por el backend; no se persiste. */
  amount_eur: number;
  units: number | null;
  previous_amount: number | null;
  previous_units: number | null;
}

export interface CategoryDetailResponse {
  year: number;
  month: number;
  category_id: string;
  category_name: string;
  /** true para Acciones: category_amount_eur es la suma de sus activos, no un valor manual. */
  is_computed: boolean;
  /** true solo para Acciones: sus activos llevan además nº de títulos (units). */
  has_units: boolean;
  category_amount_eur: number;
  /** Tipo USD→EUR usado para convertir activos de este mes (informativo). */
  fx_usd_to_eur: number | null;
  assets: AssetInvestmentDetail[];
  allocated_amount_eur: number;
  others_amount_eur: number;
}
