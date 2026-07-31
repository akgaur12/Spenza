"""Pydantic v2 request/response schemas for the `categories` module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.modules.categories.models import Category
from src.modules.categories.validators import validate_category_name

# ── Requests (user) ──────────────────────────────────────────────────────────


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Gym", "icon": "🏋️"}})

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_category_name(value)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Fitness"}})

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_category_name(value)


# ── Requests (admin) ─────────────────────────────────────────────────────────
#
# Admin category creation takes the exact same shape as a user's
# (`name` + `icon`) — `CategoryCreate` is reused rather than duplicated;
# only the ownership (`user_id=None`) and endpoint/authorization differ.
# `AdminCategoryUpdate` genuinely differs (adds `is_active`), so it stays
# separate from `CategoryUpdate`.


class AdminCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    model_config = ConfigDict(json_schema_extra={"example": {"is_active": False}})

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_category_name(value)


# ── Responses ─────────────────────────────────────────────────────────────────


class CategoryListItem(BaseModel):
    """Compact shape used in `GET /categories` listings."""

    id: uuid.UUID
    name: str
    icon: str | None
    is_system: bool


class CategoryResponse(CategoryListItem):
    """Full shape used for create/update/get and admin listings."""

    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryListResponse(BaseModel):
    items: list[CategoryListItem]


class AdminCategoryListResponse(BaseModel):
    items: list[CategoryResponse]


def to_list_item(category: Category) -> CategoryListItem:
    return CategoryListItem(
        id=category.id,
        name=category.name,
        icon=category.icon,
        is_system=category.user_id is None,
    )


def to_response(category: Category) -> CategoryResponse:
    return CategoryResponse(
        id=category.id,
        name=category.name,
        icon=category.icon,
        is_system=category.user_id is None,
        is_active=category.is_active,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )
