"""Business logic for expense export.

Expense retrieval is delegated entirely to `ExpenseRepository.list_for_export`
(the existing filtering logic, extended with an export-appropriate
chronological ordering) — this module only shapes the result into
`ExportRow`s and picks a formatter. See `export_formatters.py` for the
CSV/XLSX/PDF byte-building itself.
"""

import uuid
from datetime import UTC, date, datetime
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


def _export_filename(export_format: str, start_date: date | None, end_date: date | None) -> str:
    if start_date is not None and end_date is not None:
        return f"expenses-{start_date.isoformat()}-to-{end_date.isoformat()}.{export_format}"
    today = datetime.now(UTC).astimezone(APP_TIMEZONE).date()
    return f"expenses-{today.isoformat()}.{export_format}"


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
        category_id: uuid.UUID | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        search: str | None,
    ) -> StreamingResponse:
        expenses = await self._expenses.list_for_export(
            user.id,
            category_id=category_id,
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

        filename = _export_filename(export_format, start_date, end_date)
        return StreamingResponse(
            iter([body]),
            media_type=_CONTENT_TYPES[export_format],
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
