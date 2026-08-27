export interface Contribution {
  id: string;
  entity_id: string;
  contribution_date: string;
  amount: number;
  notes: string | null;
}

export interface ContributionCreate {
  contribution_date: string;
  amount: number;
  notes?: string | null;
}

export interface EntityContributionsResponse {
  entity_id: string;
  year: number;
  month: number;
  contributions: Contribution[];
  previous_static_total: number;
  contributions_total: number;
  projected_total: number;
  cumulative_invested_preview: number;
}
