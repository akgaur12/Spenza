"""Pydantic v2 response schemas for the `dashboard` module."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TodaySummary(BaseModel):
    total: Decimal
    expense_count: int


class WeekSummary(BaseModel):
    total: Decimal
    expense_count: int
    daily_average: Decimal


class MonthSummary(BaseModel):
    total: Decimal
    expense_count: int
    daily_average: Decimal
    average_expense: Decimal


class YearSummary(BaseModel):
    total: Decimal
    expense_count: int
    monthly_average: Decimal
    average_expense: Decimal


class PreviousMonthSummary(BaseModel):
    total: Decimal
    expense_count: int


class MonthComparison(BaseModel):
    difference: Decimal
    percentage_change: float | None = Field(
        default=None,
        description=(
            "Percentage change in spending versus the previous month. `null` when "
            "the previous month had zero spend and this month has spend greater "
            "than zero — percentage growth from a zero base is mathematically "
            "undefined."
        ),
    )
    trend: Literal["up", "down", "same"]


class DashboardCategorySummary(BaseModel):
    category_id: uuid.UUID
    name: str
    icon: str | None
    total: Decimal
    expense_count: int
    percentage: float


class LargestExpenseCategory(BaseModel):
    id: uuid.UUID
    name: str
    icon: str | None


class LargestExpenseSummary(BaseModel):
    id: uuid.UUID
    description: str
    amount: Decimal
    spent_at: datetime
    category: LargestExpenseCategory


class DashboardSummaryResponse(BaseModel):
    today: TodaySummary
    this_week: WeekSummary
    this_month: MonthSummary
    this_year: YearSummary
    previous_month: PreviousMonthSummary
    month_comparison: MonthComparison
    top_category: DashboardCategorySummary | None
    largest_expense: LargestExpenseSummary | None
