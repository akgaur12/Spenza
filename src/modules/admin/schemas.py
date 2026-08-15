"""Pydantic v2 response schemas for the cross-cutting `admin` module."""

from decimal import Decimal

from pydantic import BaseModel


class UserStats(BaseModel):
    total: int
    active: int
    inactive: int
    verified: int
    admins: int
    locked: int
    signups_last_7_days: int
    signups_last_30_days: int


class ExpenseStats(BaseModel):
    total_count: int
    total_amount: Decimal
    created_last_30_days: int


class RecurringExpenseStats(BaseModel):
    total: int
    active: int


class CategoryStats(BaseModel):
    system_count: int
    custom_count: int


class NotificationStats(BaseModel):
    total_sent: int
    delivery_failures_last_7_days: int


class AdminStatsOverview(BaseModel):
    users: UserStats
    expenses: ExpenseStats
    recurring_expenses: RecurringExpenseStats
    categories: CategoryStats
    notifications: NotificationStats
