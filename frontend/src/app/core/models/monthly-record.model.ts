import { Entity } from './entity.model';

export interface EntityBalance {
  entity_id: string;
  balance_amount: number;
  entity?: Entity | null;
}

export interface EntityBalanceInput {
  entity_id: string;
  balance_amount: number;
}

export interface MonthlyRecordUpsert {
  balances: EntityBalanceInput[];
}

export interface MonthlyRecord {
  id: number;
  year: number;
  month: number;
  total_liquid: number;
  total_invested: number;
  total_net_worth: number;
  monthly_diff: number | null;
  invested_percentage: number;
  created_at: string;
  balances: EntityBalance[];
}

export interface MonthlyRecordResponse {
  exists: boolean;
  year: number;
  month: number;
  record: MonthlyRecord | null;
  previous_net_worth: number | null;
}

export interface ImportJsonResponse {
  status: string;
  imported_count: number;
  detail: string;
}
