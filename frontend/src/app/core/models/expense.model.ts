export interface ExpenseItemDetail {
  concept: string;
  amount: number;
  count: number;
}

export interface CategoryExpense {
  category: string;
  category_name: string;
  color: string;
  amount: number;
  percentage: number;
  items?: ExpenseItemDetail[];
}

export interface MonthlyExpensesResponse {
  year: number;
  month: number;
  total_amount: number;
  categories: CategoryExpense[];
  has_expenses: boolean;
  imported_months?: string[];
  imported_sources?: string[];
  skipped_months?: string[];
}
