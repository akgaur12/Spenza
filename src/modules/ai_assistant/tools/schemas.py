"""LangChain `args_schema` models for every tool.

Every field here is a business parameter (category, date range, period,
search term, ...) an LLM may fill in. None of these models ever declares a
`user`/`user_id` field — `ToolContext` supplies the trusted user via
closure (see `context.py`), never as a model-fillable argument. Tests in
`tests/ai_assistant/tools/` assert this directly against every tool's
`args_schema`.
"""

import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from src.modules.analytics.schemas import TrendInterval
from src.modules.recurring_expenses.enums import Frequency, RecurringExpenseStatus

_DATE_DESC = "ISO date (YYYY-MM-DD)."

_LOOSE_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def _normalize_date_string(value: object) -> object:
    """Smaller/local models often emit dates without zero-padding (e.g.
    "2026-7-1" instead of "2026-07-01"), which pydantic's strict ISO-8601
    date parser rejects outright as "too short". Reformat the string
    before validation so a tool call doesn't fail purely over formatting
    — pydantic's normal date parsing still runs on the result.
    """
    if isinstance(value, str):
        match = _LOOSE_DATE_RE.match(value.strip())
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return value


LenientDate = Annotated[date, BeforeValidator(_normalize_date_string)]


class NoArgs(BaseModel):
    """For tools that take no parameters at all."""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class DateRangeArgs(BaseModel):
    start_date: LenientDate | None = Field(
        default=None, description=f"Start of the date range (inclusive). {_DATE_DESC}"
    )
    end_date: LenientDate | None = Field(
        default=None, description=f"End of the date range (inclusive). {_DATE_DESC}"
    )


class GetExpensesArgs(DateRangeArgs):
    category: str | None = Field(default=None, description="Category name to filter by.")
    min_amount: float | None = Field(default=None, gt=0)
    max_amount: float | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class SearchExpensesArgs(DateRangeArgs):
    search_term: str = Field(
        ..., min_length=1, max_length=255, description="Text to search for in expense descriptions."
    )
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class GetExpenseArgs(BaseModel):
    expense_id: str = Field(
        ..., description="The exact expense id, e.g. from a prior get_expenses/search result."
    )


class GetTotalSpendingArgs(DateRangeArgs):
    pass


class GetSpendingTrendsArgs(DateRangeArgs):
    interval: TrendInterval = Field(
        ..., description="Bucket size: daily, weekly, monthly, or yearly."
    )


class GetCategorySpendingArgs(DateRangeArgs):
    pass


class GetTopCategoriesArgs(DateRangeArgs):
    limit: int = Field(default=5, ge=1, le=20)


class GetLargestExpensesArgs(DateRangeArgs):
    limit: int = Field(default=5, ge=1, le=20)


class ComparePeriodsArgs(BaseModel):
    start_date: LenientDate = Field(
        ..., description=f"Start of the period to analyze. {_DATE_DESC}"
    )
    end_date: LenientDate = Field(..., description=f"End of the period to analyze. {_DATE_DESC}")


class GetCategoriesArgs(BaseModel):
    search: str | None = Field(default=None, max_length=255)


class CompareCategoriesArgs(BaseModel):
    start_date: LenientDate = Field(
        ..., description=f"Start of the period to analyze. {_DATE_DESC}"
    )
    end_date: LenientDate = Field(..., description=f"End of the period to analyze. {_DATE_DESC}")


class GetRecurringExpensesArgs(BaseModel):
    status: RecurringExpenseStatus | None = None
    frequency: Frequency | None = None
    search: str | None = Field(default=None, max_length=255)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class GetUpcomingRecurringExpensesArgs(BaseModel):
    days_ahead: int = Field(default=30, ge=1, le=365)


class GetReportSummaryArgs(DateRangeArgs):
    pass
