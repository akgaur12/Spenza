"""`import_router`/`export_router`: bulk expense import and export.

Every route requires authentication via `CurrentUser`. Ownership is always
derived from `CurrentUser`, never accepted from the request body, matching
the `expenses` module — imported rows always belong to the current user, and
exports only ever cover the current user's own expenses.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from src.core.responses import SuccessResponse
from src.modules.import_export.dependencies import get_export_service, get_import_service
from src.modules.import_export.export_service import ExportFormat, ExportService
from src.modules.import_export.import_service import ImportService
from src.modules.import_export.schemas import (
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportResult,
)
from src.modules.users.dependencies import CurrentUser

import_router = APIRouter(prefix="/api/v1/import/expenses", tags=["import"])
export_router = APIRouter(prefix="/api/v1/export/expenses", tags=["export"])


@import_router.post(
    "/preview",
    response_model=SuccessResponse[ImportPreviewResponse],
    summary="Validate an expense import file without inserting anything",
)
async def preview_import(
    current_user: CurrentUser,
    import_service: Annotated[ImportService, Depends(get_import_service)],
    file: Annotated[UploadFile, File()],
) -> SuccessResponse[ImportPreviewResponse]:
    result = await import_service.preview(current_user, file)
    return SuccessResponse(message="OK", data=result)


@import_router.post(
    "/confirm",
    response_model=SuccessResponse[ImportResult],
    summary="Insert the rows validated by a previous preview",
)
async def confirm_import(
    data: ImportConfirmRequest,
    current_user: CurrentUser,
    import_service: Annotated[ImportService, Depends(get_import_service)],
) -> SuccessResponse[ImportResult]:
    result = await import_service.confirm(current_user, data)
    return SuccessResponse(message="Import completed", data=result)


@export_router.get(
    "",
    summary="Export the current user's expenses as CSV, XLSX, or PDF",
)
async def export_expenses(
    current_user: CurrentUser,
    export_service: Annotated[ExportService, Depends(get_export_service)],
    export_format: Annotated[ExportFormat, Query(alias="format")],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    min_amount: Annotated[Decimal | None, Query(gt=0)] = None,
    max_amount: Annotated[Decimal | None, Query(gt=0)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> StreamingResponse:
    return await export_service.export(
        current_user,
        export_format=export_format,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        min_amount=min_amount,
        max_amount=max_amount,
        search=search,
    )
