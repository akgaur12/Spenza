"""Integration tests for GET /api/v1/export/expenses?format=pdf.

Per the spec, these deliberately avoid fragile pixel-perfect PDF assertions
and instead check structural validity (a well-formed PDF) plus that the
expected report text made it into the rendered output — reliable since
`export_formatters.build_pdf_export` disables stream compression precisely
so this content stays inspectable as plain bytes without a PDF-parsing
dependency.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import (
    category_id_by_name,
    create_expense,
    login_user_a,
    login_user_b,
)


async def test_export_pdf_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert response.status_code == 401


async def test_export_pdf_content_type_and_filename(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert ".pdf" in response.headers["content-disposition"]


async def test_export_pdf_is_structurally_valid(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content


async def test_export_pdf_report_title(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert b"Expense Report" in response.content


async def test_export_pdf_date_range_represented(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get(
        "/api/v1/export/expenses",
        params={"format": "pdf", "start_date": "2025-01-01", "end_date": "2025-01-31"},
    )
    assert b"01-Jan-2025" in response.content
    assert b"31-Jan-2025" in response.content


async def test_export_pdf_totals_and_rows_represented(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Cake",
        amount="278.00",
        spent_at="2025-01-01T00:00:00+05:30",
    )
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    content = response.content
    assert b"Total Expenses: 1" in content
    assert b"278.00" in content
    assert b"Cake" in content
    assert b"Food" in content
    assert b"Wed" in content


async def test_export_pdf_many_rows_span_multiple_pages(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    start = datetime(2025, 1, 1, tzinfo=UTC)
    row_count = 90
    for offset in range(row_count):
        spent_at = (start + timedelta(days=offset)).isoformat()
        await create_expense(
            client,
            category_id=food_id,
            description=f"Expense {offset}",
            amount="10.00",
            spent_at=spent_at,
        )
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert response.status_code == 200
    assert f"Total Expenses: {row_count}".encode() in response.content
    # `/Type /Page` matches both the `/Pages` tree root and each page leaf —
    # more than 2 occurrences means at least 2 real page objects were
    # emitted, i.e. the table actually paginated rather than clipping.
    assert response.content.count(b"/Type /Page") > 2


async def test_export_pdf_user_isolation(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_b(client, email_backend)
    food_id_b = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id_b, spent_at="2025-01-01T00:00:00+05:30", description="OnlyUserB"
    )

    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert b"OnlyUserB" not in response.content
    assert b"Total Expenses: 0" in response.content


async def test_export_pdf_empty_report(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "pdf"})
    assert response.status_code == 200
    assert b"Total Expenses: 0" in response.content
    assert b"No expenses found for the selected period." in response.content
