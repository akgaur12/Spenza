"""Pydantic v2 request/response schemas for the `expenses` module."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.modules.categories.models import Category
from src.modules.expenses.models import Expense
from src.modules.expenses.validators import validate_description

# ── Requests ──────────────────────────────────────────────────────────────


class ExpenseCreate(BaseModel):
    category_id: uuid.UUID
    description: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    spent_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category_id": "5e2f3f3a-8b8a-4b1a-9a1a-6f6a1e2c9d10",
                "description": "Cake",
                "amount": "278.00",
                "spent_at": "2025-01-01T00:00:00+05:30",
            }
        }
    )

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return validate_description(value)


class ExpenseUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    spent_at: datetime | None = None

    model_config = ConfigDict(json_schema_extra={"example": {"amount": "300.00"}})

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_description(value)


# ── Responses ─────────────────────────────────────────────────────────────


class ExpenseCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    icon: str | None


class ExpenseResponse(BaseModel):
    id: uuid.UUID
    description: str
    amount: Decimal
    spent_at: datetime
    category: ExpenseCategoryResponse
    created_at: datetime
    updated_at: datetime


class ExpenseListResponse(BaseModel):
    items: list[ExpenseResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def to_response(expense: Expense, category: Category) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense.id,
        description=expense.description,
        amount=expense.amount,
        spent_at=expense.spent_at,
        category=ExpenseCategoryResponse(id=category.id, name=category.name, icon=category.icon),
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )
