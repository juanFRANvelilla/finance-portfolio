import { Entity } from './entity.model';

export interface EntityBalance {
  entity_id: string;
  balance_amount: number;
  entity?: Entity | null;
}

export interface HybridAccount {
  entity_id: string;
  liquid_amount: number;
  monthly_contribution: number;
  cumulative_invested: number;
  entity?: Entity | null;
}

export interface EntityBalanceInput {
  entity_id: string;
  balance_amount: number;
}

export interface MonthlyRecordUpsert {
  balances: EntityBalanceInput[];
}

/** DTO con totales calculados al vuelo por el backend. */
export interface MonthlyRecord {
  id: string;
  year: number;
  month: number;
  created_at: string;
  balances: EntityBalance[];
  hybrid_accounts: HybridAccount[];
  total_liquid: number;
  total_invested: number;
  total_net_worth: number;
  invested_percentage: number;
  monthly_diff: number | null;
  invested_diff: number | null;
}

export interface MonthlyRecordResponse {
  exists: boolean;
  year: number;
  month: number;
  record: MonthlyRecord | null;
  previous_net_worth: number | null;
  previous_total_invested: number | null;
}

export interface TimelinePoint {
  year: number;
  month: number;
  total_net_worth: number;
  total_invested: number;
  net_worth_diff: number | null;
  invested_diff: number | null;
}

export interface TimelineResponse {
  points: TimelinePoint[];
}

export interface SimpleBalanceImport {
  entity_id: string;
  amount: number;
}

export interface HybridBalanceImport {
  entity_id: string;
  liquid_amount: number;
  invested_amount: number;
}

export interface ExpectedTotalsImport {
  total_liquid: number;
  total_invested: number;
  total_net_worth: number;
}

export interface ImportPayload {
  simple_balances: SimpleBalanceImport[];
  hybrid_balances: HybridBalanceImport[];
  expected_totals: ExpectedTotalsImport;
}
