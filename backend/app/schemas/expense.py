from pydantic import BaseModel, ConfigDict, Field


class ExpenseItemDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    concept: str
    amount: float
    count: int = 1


class CategoryExpenseItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    category_name: str
    color: str
    amount: float
    percentage: float
    items: list[ExpenseItemDetail] = Field(default_factory=list)


class MonthlyExpensesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year: int
    month: int
    total_amount: float
    categories: list[CategoryExpenseItem]
    has_expenses: bool
    imported_months: list[str] = Field(default_factory=list)
    imported_sources: list[str] = Field(default_factory=list)
    skipped_months: list[str] = Field(default_factory=list)
