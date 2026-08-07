"""Orchestration for the `reports` module.

Responsibilities, and only these: validate/resolve the request, call the
existing `dashboard`/`analytics` services and the `expenses` repository for
the resolved period, hand everything to `ReportBuilder`, render the PDF, and
return it. No HTML, no PDF rendering, no calculations — see `builder.py` for
where the (presentation-only) arithmetic lives, and `pdf_generator.py` for
rendering.

Reuses services rather than the database directly wherever a service method
already covers the query — `DashboardService.get_range_summary()` (added
alongside this module) and `AnalyticsService`'s existing category/trend/
heatmap methods. The one exception is `ExpenseRepository.list_for_export()`
for the expense table: no *service* exposes an unpaginated "all expenses in
a range" listing, so this module depends on the repository directly for
that single call — exactly how `import_export.ExportService` already does
for the same reason.
"""

from datetime import datetime, timedelta

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.timezone import APP_TIMEZONE, local_midnight_utc
from src.modules.analytics.schemas import CalendarHeatmapResponse, TrendInterval
from src.modules.analytics.service import AnalyticsService
from src.modules.dashboard.service import DashboardService
from src.modules.expenses.repository import ExpenseRepository
from src.modules.import_export.export_formatters import ExportRow
from src.modules.reports.builder import MonthlyCategoryInput, ReportBuilder, ReportInputs
from src.modules.reports.date_range_resolver import (
    ResolvedDateRange,
    month_buckets,
    previous_period,
    resolve_date_range,
)
from src.modules.reports.exceptions import ReportGenerationFailedError
from src.modules.reports.pdf_generator import PDFGenerator
from src.modules.reports.schemas import ReportRequest, ReportType
from src.modules.users.models import User

# Beyond this span, a custom report's calendar heatmap would need to render
# many months of near-empty grids for little insight — summarized away with
# a note instead (see the task's "very large ranges" allowance).
CUSTOM_HEATMAP_MAX_SPAN_DAYS = 186


def _utc_bounds(resolved: ResolvedDateRange) -> tuple[datetime, datetime]:
    return (
        local_midnight_utc(resolved.start_date),
        local_midnight_utc(resolved.end_date + timedelta(days=1)),
    )


def _resolve_heatmap_years(
    report_type: ReportType, resolved: ResolvedDateRange
) -> list[int] | None:
    """`None` means "don't fetch a heatmap at all" (see `CUSTOM_HEATMAP_MAX_SPAN_DAYS`).
    Otherwise, every calendar year the resolved range touches — usually one,
    but a custom range may straddle a year boundary.
    """
    if report_type is ReportType.CUSTOM and resolved.span_days > CUSTOM_HEATMAP_MAX_SPAN_DAYS:
        return None
    return list(range(resolved.start_date.year, resolved.end_date.year + 1))


def _report_filename(report_type: ReportType, resolved: ResolvedDateRange) -> str:
    if report_type is ReportType.MONTHLY:
        suffix = f"{resolved.start_date.year:04d}-{resolved.start_date.month:02d}"
    elif report_type is ReportType.QUARTERLY:
        quarter = (resolved.start_date.month - 1) // 3 + 1
        suffix = f"{resolved.start_date.year:04d}-Q{quarter}"
    elif report_type is ReportType.YEARLY:
        suffix = f"{resolved.start_date.year:04d}"
    else:
        suffix = f"{resolved.start_date.isoformat()}_to_{resolved.end_date.isoformat()}"
    return f"{report_type.value}-report-{suffix}.pdf"


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._dashboard = DashboardService(session)
        self._analytics = AnalyticsService(session)
        self._expenses = ExpenseRepository(session)
        self._builder = ReportBuilder()
        self._pdf = PDFGenerator()

    async def generate(self, user: User, request: ReportRequest) -> StreamingResponse:
        today = datetime.now(APP_TIMEZONE).date()
        resolved = resolve_date_range(request, today)
        previous = previous_period(resolved)

        start_utc, end_utc = _utc_bounds(resolved)
        prev_start_utc, prev_end_utc = _utc_bounds(previous)

        range_summary = await self._dashboard.get_range_summary(
            user, start_utc, end_utc, resolved.span_days
        )
        previous_summary = await self._dashboard.get_range_summary(
            user, prev_start_utc, prev_end_utc, previous.span_days
        )
        category_breakdown = await self._analytics.get_category_breakdown(
            user, resolved.start_date, resolved.end_date
        )

        daily_trend = await self._analytics.get_trends(
            user, TrendInterval.DAILY, resolved.start_date, resolved.end_date
        )
        weekly_trend = await self._analytics.get_trends(
            user, TrendInterval.WEEKLY, resolved.start_date, resolved.end_date
        )
        monthly_trend = await self._analytics.get_trends(
            user, TrendInterval.MONTHLY, resolved.start_date, resolved.end_date
        )

        monthly_category = [
            MonthlyCategoryInput(
                period=bucket,
                breakdown=await self._analytics.get_category_breakdown(
                    user, bucket.start_date, bucket.end_date
                ),
            )
            for bucket in month_buckets(resolved)
        ]

        heatmap_years = _resolve_heatmap_years(request.type, resolved)
        heatmap_by_year: dict[int, CalendarHeatmapResponse] = {}
        heatmap_note: str | None = None
        if heatmap_years is None:
            heatmap_note = (
                f"Calendar heatmap omitted: the selected range spans "
                f"{resolved.span_days} days, too large to render practically."
            )
        else:
            for year in heatmap_years:
                heatmap_by_year[year] = await self._analytics.get_calendar_heatmap(user, year)

        expenses = await self._expenses.list_for_export(
            user.id,
            start_date=resolved.start_date,
            end_date=resolved.end_date,
            limit=settings.MAX_EXPORT_ROWS,
        )
        export_rows = [
            ExportRow(
                spent_date=expense.spent_at.astimezone(APP_TIMEZONE).date(),
                category_name=expense.category.name,
                description=expense.description,
                amount=expense.amount,
            )
            for expense in expenses
        ]

        data = self._builder.build(
            ReportInputs(
                user=user,
                request=request,
                resolved=resolved,
                generated_at=datetime.now(APP_TIMEZONE),
                range_summary=range_summary,
                previous_summary=previous_summary,
                category_breakdown=category_breakdown,
                daily_trend=daily_trend,
                weekly_trend=weekly_trend,
                monthly_trend=monthly_trend,
                monthly_category=monthly_category,
                heatmap_by_year=heatmap_by_year,
                heatmap_note=heatmap_note,
                expenses=export_rows,
            )
        )

        try:
            pdf_bytes = self._pdf.generate(request.type, data)
        except Exception as exc:
            raise ReportGenerationFailedError() from exc

        filename = _report_filename(request.type, resolved)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
