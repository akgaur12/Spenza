"""Pydantic v2 request/response schemas for the `recurring_expenses` module."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.modules.categories.models import Category
from src.modules.expenses.validators import validate_description
from src.modules.recurring_expenses.enums import Frequency, GenerationMode, RecurringExpenseStatus
from src.modules.recurring_expenses.models import RecurringExpense
from src.modules.recurring_expenses.validators import validate_date_range

# ── Requests ──────────────────────────────────────────────────────────────


class RecurringExpenseCreate(BaseModel):
    category_id: uuid.UUID
    description: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    frequency: Frequency
    generation_mode: GenerationMode = GenerationMode.AUTO
    start_date: date
    end_date: date | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category_id": "5e2f3f3a-8b8a-4b1a-9a1a-6f6a1e2c9d10",
                "description": "Netflix Subscription",
                "amount": "649.00",
                "frequency": "monthly",
                "generation_mode": "auto",
                "start_date": "2026-08-01",
            }
        }
    )

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return validate_description(value)

    @model_validator(mode="after")
    def _dates(self) -> "RecurringExpenseCreate":
        validate_date_range(self.start_date, self.end_date)
        return self


class RecurringExpenseUpdate(BaseModel):
    """All fields optional (`PATCH` semantics). `status` accepts only
    `cancelled` — `ACTIVE`/`PAUSED` have their own `/pause` and `/resume`
    endpoints, and `COMPLETED` is system-managed — enforced in the service,
    not here, since that's a business rule rather than request shape.
    Cross-field date-range validation also happens in the service, where
    the existing record's `start_date`/`end_date` are available to merge
    with whichever half of the pair this request actually changed.
    """

    category_id: uuid.UUID | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    frequency: Frequency | None = None
    generation_mode: GenerationMode | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: RecurringExpenseStatus | None = None

    model_config = ConfigDict(json_schema_extra={"example": {"amount": "699.00"}})

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_description(value)


# ── Responses ─────────────────────────────────────────────────────────────


class RecurringExpenseCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    icon: str | None


class RecurringExpenseResponse(BaseModel):
    id: uuid.UUID
    description: str
    amount: Decimal
    category: RecurringExpenseCategoryResponse
    frequency: Frequency
    generation_mode: GenerationMode
    status: RecurringExpenseStatus
    start_date: date
    end_date: date | None
    next_run_date: date
    last_run_date: date | None
    created_at: datetime
    updated_at: datetime


class RecurringExpenseListResponse(BaseModel):
    items: list[RecurringExpenseResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def to_response(recurring: RecurringExpense, category: Category) -> RecurringExpenseResponse:
    return RecurringExpenseResponse(
        id=recurring.id,
        description=recurring.description,
        amount=recurring.amount,
        category=RecurringExpenseCategoryResponse(
            id=category.id, name=category.name, icon=category.icon
        ),
        frequency=recurring.frequency,
        generation_mode=recurring.generation_mode,
        status=recurring.status,
        start_date=recurring.start_date,
        end_date=recurring.end_date,
        next_run_date=recurring.next_run_date,
        last_run_date=recurring.last_run_date,
        created_at=recurring.created_at,
        updated_at=recurring.updated_at,
    )
