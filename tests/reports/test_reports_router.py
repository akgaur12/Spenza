"""Integration tests for `POST /api/v1/reports/generate`.

Like the export PDF tests, these avoid pixel-perfect assertions and instead
check structural validity (a well-formed PDF) plus that expected text made
it into the rendered output. Unlike the ReportLab-based export PDFs (which
disable stream compression to stay grep-able as raw bytes), WeasyPrint
always renders text via embedded subset-font glyph indices — never literal
ASCII — regardless of compression, so text assertions here go through
`pypdf` instead of a raw `in response.content` check.
"""

import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.expenses.repository import ExpenseRepository
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import (
    USER_A,
    category_id_by_name,
    create_expense,
    login_user_a,
    login_user_b,
)


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


async def test_generate_report_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 401


async def test_monthly_report_content_type_and_filename(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == (
        'attachment; filename="monthly-report-2026-07.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content


async def test_quarterly_report(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "quarterly", "year": 2026, "quarter": 2}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        'attachment; filename="quarterly-report-2026-Q2.pdf"'
    )
    assert "Q2 2026" in _extract_text(response.content)


async def test_quarterly_report_hides_expense_table(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "quarterly", "year": 2026, "quarter": 2}
    )
    assert response.status_code == 200
    assert "Expense Table" not in _extract_text(response.content)


async def test_yearly_report(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    response = await client.post("/api/v1/reports/generate", json={"type": "yearly", "year": 2025})
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        'attachment; filename="yearly-report-2025.pdf"'
    )


async def test_yearly_report_uses_yearly_specific_sections(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Cake",
        amount="278.00",
        spent_at="2025-03-15T00:00:00+05:30",
    )
    response = await client.post("/api/v1/reports/generate", json={"type": "yearly", "year": 2025})
    assert response.status_code == 200
    text = _extract_text(response.content)

    assert "Monthly Spending Trend" in text
    assert "Daily Spending Trend" not in text
    assert "Weekly Spending Trend" in text
    assert "Weekday Spending Trends" in text
    assert "Category Analysis" in text
    assert "Calendar Heatmap" in text
    assert "Category Breakdown" in text
    assert "Top Expenses" in text
    assert "Expense Table" not in text
    assert "Highest Spending Month" in text


async def test_custom_report(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-01-01", "end_date": "2026-06-30"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        'attachment; filename="custom-report-2026-01-01_to_2026-06-30.pdf"'
    )


async def test_custom_report_key_metrics_matches_yearly_layout(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-01-01", "end_date": "2026-06-30"},
    )
    assert response.status_code == 200
    text = _extract_text(response.content)
    assert "Average Monthly Spending" in text
    assert "Top Category" in text
    # Unlike yearly/quarterly, a custom range has no natural "previous
    # period" to compare against in the highlight card or Key Metrics —
    # it shows Avg. Daily Spending in the card slot instead.
    assert "Vs. Previous Period" not in text
    # The highlight-card label is rendered all-caps via CSS `text-transform`,
    # which WeasyPrint bakes into the actual extracted glyphs (unlike a
    # browser, where it's a purely visual effect over unchanged DOM text).
    assert "AVG. DAILY SPENDING" in text


async def test_report_reflects_expense_data(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Cake",
        amount="278.00",
        spent_at="2026-07-01T00:00:00+05:30",
    )
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200
    text = _extract_text(response.content)
    assert "Cake" in text
    assert "278.00" in text
    assert "Food" in text


async def test_report_includes_all_redesigned_sections(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Cake",
        amount="278.00",
        spent_at="2026-07-15T00:00:00+05:30",
    )
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200
    text = _extract_text(response.content)

    # Header: user identity, no separate title-only cover page.
    assert "user_a" in text or "user.a@example.com" in text

    # Redesigned section headings.
    for heading in (
        "Key Metrics",
        "Spending Insights",
        "Daily Spending Trend",
        "Weekly Spending Trend",
        "Weekday Spending Trends",
        "Category Analysis",
        "Calendar Heatmap",
        "Category Breakdown",
        "Top Expenses",
        "Expense Table",
    ):
        assert heading in text, f"missing section: {heading}"

    # Weekday Spending Trends and Category Analysis are stacked full-width
    # rows, in that order — not side-by-side columns.
    assert text.index("Weekday Spending Trends") < text.index("Category Analysis")

    assert "Generated by Spenza" in text
    assert "All rights reserved" in text


async def test_report_empty_period_still_generates(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200
    assert "No expenses found for the selected period." in _extract_text(response.content)


async def test_report_user_isolation(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_b(client, email_backend)
    food_id_b = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id_b,
        spent_at="2026-07-01T00:00:00+05:30",
        description="OnlyUserB",
    )

    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200
    assert "OnlyUserB" not in _extract_text(response.content)


async def test_monthly_report_spanning_many_pages(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    # Inserted directly rather than via 60 sequential HTTP round-trips —
    # this test only cares that a large expense table paginates and repeats
    # its header, not that expense creation itself works (covered elsewhere).
    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(USER_A["email"])
        assert user is not None
        expenses = ExpenseRepository(session)
        start = datetime(2026, 7, 1, tzinfo=UTC)
        for offset in range(60):
            expenses.create(
                user_id=user.id,
                category_id=uuid.UUID(food_id),
                description=f"Expense {offset}",
                amount=Decimal("10.00"),
                spent_at=start + timedelta(hours=offset * 6),
            )
        await session.commit()

    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200
    assert len(PdfReader(io.BytesIO(response.content)).pages) > 2


# ── Validation ────────────────────────────────────────────────────────────


async def test_monthly_missing_month_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post("/api/v1/reports/generate", json={"type": "monthly", "year": 2026})
    assert response.status_code == 400
    assert response.json()["error_code"] == "MISSING_REPORT_FIELDS"


async def test_monthly_invalid_month_is_rejected_by_schema(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 13}
    )
    assert response.status_code == 422


async def test_yearly_invalid_year_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post("/api/v1/reports/generate", json={"type": "yearly", "year": 2099})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_REPORT_YEAR"


async def test_future_month_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 12}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "FUTURE_REPORT_PERIOD"


async def test_custom_invalid_date_range_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-06-30", "end_date": "2026-01-01"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_REPORT_DATE_RANGE"


async def test_cross_type_fields_are_rejected_by_schema(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "monthly", "year": 2026, "month": 7, "quarter": 2},
    )
    assert response.status_code == 422


async def test_date_range_on_non_custom_type_is_rejected_by_schema(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={
            "type": "yearly",
            "year": 2026,
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    )
    assert response.status_code == 422


async def test_year_on_custom_type_is_rejected_by_schema(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={
            "type": "custom",
            "year": 2026,
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    )
    assert response.status_code == 422


async def test_month_on_non_monthly_type_is_rejected_by_schema(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "yearly", "year": 2026, "month": 7}
    )
    assert response.status_code == 422


async def test_custom_report_short_span(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-07-01", "end_date": "2026-07-10"},
    )
    assert response.status_code == 200


async def test_custom_report_under_one_month_hides_average_monthly_spending(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-07-01", "end_date": "2026-07-05"},
    )
    assert response.status_code == 200
    # A 5-day span is entirely within one calendar month, so "Average Monthly
    # Spending" would just equal Total Spending — redundant and misleading
    # labeled as a monthly rate, so it's hidden rather than shown as a
    # duplicate of Total Spending.
    assert "Average Monthly Spending" not in _extract_text(response.content)


async def test_custom_report_medium_span(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-04-01", "end_date": "2026-06-30"},
    )
    assert response.status_code == 200


async def test_custom_report_very_large_span_generates_successfully(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2022-01-01", "end_date": "2026-01-01"},
    )
    assert response.status_code == 200
    # Custom reports never show a Calendar Heatmap section, so a too-large
    # span has nothing to omit — it just generates like any other span.
    assert "Calendar Heatmap" not in _extract_text(response.content)


async def test_custom_report_hides_calendar_heatmap(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate",
        json={"type": "custom", "start_date": "2026-01-01", "end_date": "2026-06-30"},
    )
    assert response.status_code == 200
    assert "Calendar Heatmap" not in _extract_text(response.content)


async def test_pdf_generation_failure_is_reported_as_server_error(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.modules.reports.pdf_generator import PDFGenerator
    from src.modules.reports.schemas import ReportData, ReportType

    def _boom(self: PDFGenerator, report_type: ReportType, data: ReportData) -> bytes:
        raise RuntimeError("rendering exploded")

    monkeypatch.setattr(PDFGenerator, "generate", _boom)

    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/reports/generate", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "REPORT_GENERATION_FAILED"
