"""Pydantic v2 request/response schemas for the `analytics` module."""

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class TrendInterval(StrEnum):
    """Bucket granularity for `GET /api/v1/analytics/trends`."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class CategoryAnalyticsItem(BaseModel):
    category_id: uuid.UUID
    name: str
    icon: str | None
    total: Decimal
    expense_count: int
    percentage: float
    average_expense: Decimal


class CategoryAnalyticsResponse(BaseModel):
    start_date: date
    end_date: date
    total_spending: Decimal
    expense_count: int
    categories: list[CategoryAnalyticsItem]


class TrendDataPoint(BaseModel):
    period: str
    start_date: date | None = Field(
        default=None, description="Bucket start date. Only populated for weekly buckets."
    )
    end_date: date | None = Field(
        default=None, description="Bucket end date (inclusive). Only populated for weekly buckets."
    )
    total: Decimal
    expense_count: int
    average_expense: Decimal


class TrendAnalyticsResponse(BaseModel):
    interval: TrendInterval
    start_date: date
    end_date: date
    total_spending: Decimal
    expense_count: int
    data: list[TrendDataPoint]


class CalendarHeatmapDay(BaseModel):
    date: date
    month: int
    day: int
    total: Decimal
    expense_count: int
    is_future: bool


class CalendarHeatmapResponse(BaseModel):
    year: int
    total_spending: Decimal
    expense_count: int
    max_daily_spending: Decimal
    data: list[CalendarHeatmapDay]
