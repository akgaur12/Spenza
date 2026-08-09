"""Business logic for expense export.

Expense retrieval is delegated entirely to `ExpenseRepository.list_for_export`
(the existing filtering logic, extended with an export-appropriate
chronological ordering) — this module only shapes the result into
`ExportRow`s and picks a formatter. See `export_formatters.py` for the
CSV/XLSX/PDF byte-building itself.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.timezone import APP_TIMEZONE
from src.modules.expenses.repository import ExpenseRepository
from src.modules.import_export.export_formatters import (
    ExportRow,
    build_csv_export,
    build_pdf_export,
    build_xlsx_export,
)
from src.modules.users.models import User

ExportFormat = Literal["csv", "xlsx", "pdf"]

_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _export_filename(
    export_format: str, username: str, start_date: date | None, end_date: date | None
) -> str:
    if start_date is not None and end_date is not None:
        date_range = f"{start_date.isoformat()}_to_{end_date.isoformat()}"
    else:
        date_range = "all"
    return f"spenza_{username}_{date_range}.{export_format}"


class ExportService:
    def __init__(self, session: AsyncSession) -> None:
        self._expenses = ExpenseRepository(session)

    async def export(
        self,
        user: User,
        *,
        export_format: ExportFormat,
        start_date: date | None,
        end_date: date | None,
        category_ids: list[uuid.UUID] | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        search: str | None,
    ) -> StreamingResponse:
        body, filename, content_type = await self.export_bytes(
            user,
            export_format=export_format,
            start_date=start_date,
            end_date=end_date,
            category_ids=category_ids,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
        )
        return StreamingResponse(
            iter([body]),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def export_bytes(
        self,
        user: User,
        *,
        export_format: ExportFormat,
        start_date: date | None,
        end_date: date | None,
        category_ids: list[uuid.UUID] | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        search: str | None,
    ) -> tuple[bytes, str, str]:
        """The same pipeline `export()` streams to the caller, but returning
        the raw bytes/filename/content-type instead of wrapping them in a
        `StreamingResponse` — so `UserService`'s pre-deletion data export can
        email the exact same file a manual `/export` call would download.
        """
        expenses = await self._expenses.list_for_export(
            user.id,
            category_ids=category_ids,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
            limit=settings.MAX_EXPORT_ROWS,
        )

        rows = [
            ExportRow(
                spent_date=expense.spent_at.astimezone(APP_TIMEZONE).date(),
                category_name=expense.category.name,
                description=expense.description,
                amount=expense.amount,
            )
            for expense in expenses
        ]

        if export_format == "csv":
            body = build_csv_export(rows)
        elif export_format == "xlsx":
            body = build_xlsx_export(rows)
        else:
            body = build_pdf_export(rows, start_date=start_date, end_date=end_date)

        filename = _export_filename(export_format, user.username, start_date, end_date)
        return body, filename, _CONTENT_TYPES[export_format]
