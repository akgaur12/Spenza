"""Pydantic v2 request/response schemas for the `import_export` module.

Export endpoints return files (`StreamingResponse`), not JSON, so there are
no export schemas here — only import preview/confirm.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FileType = Literal["csv", "xlsx"]


class ImportRowErrorCode(StrEnum):
    INVALID_DATE = "INVALID_DATE"
    CATEGORY_NOT_FOUND = "CATEGORY_NOT_FOUND"
    CATEGORY_INACTIVE = "CATEGORY_INACTIVE"
    CATEGORY_AMBIGUOUS = "CATEGORY_AMBIGUOUS"
    DESCRIPTION_REQUIRED = "DESCRIPTION_REQUIRED"
    DESCRIPTION_TOO_LONG = "DESCRIPTION_TOO_LONG"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    AMOUNT_MUST_BE_POSITIVE = "AMOUNT_MUST_BE_POSITIVE"
    DUPLICATE_EXPENSE = "DUPLICATE_EXPENSE"


# ── Requests ──────────────────────────────────────────────────────────────


class ImportConfirmRequest(BaseModel):
    import_token: str = Field(..., min_length=1)

    model_config = ConfigDict(json_schema_extra={"example": {"import_token": "eyJhbGciOi..."}})


# ── Preview response ─────────────────────────────────────────────────────


class ImportRowError(BaseModel):
    field: str
    code: ImportRowErrorCode
    message: str


class ImportPreviewCategory(BaseModel):
    id: uuid.UUID
    name: str


class ImportPreviewRow(BaseModel):
    row_number: int
    date: date | None
    category: ImportPreviewCategory | None
    description: str | None
    amount: Decimal | None
    valid: bool
    errors: list[ImportRowError]


class ImportPreviewResponse(BaseModel):
    import_token: str
    file_name: str
    file_type: FileType
    total_rows: int
    valid_rows: int
    invalid_rows: int
    expires_at: datetime
    rows: list[ImportPreviewRow]


# ── Confirm response ─────────────────────────────────────────────────────


class ImportResult(BaseModel):
    status: Literal["completed"]
    imported_count: int
    failed_count: int
