"""Integration tests for GET /api/v1/export/expenses?format=csv."""

import csv
import io

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import (
    category_id_by_name,
    create_expense,
    login_user_a,
    login_user_b,
)


def _parse_csv(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


# ── Auth ──────────────────────────────────────────────────────────────────


async def test_export_csv_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    assert response.status_code == 401


# ── Headers ───────────────────────────────────────────────────────────────


async def test_export_csv_content_type_and_filename(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert ".csv" in response.headers["content-disposition"]
    assert "attachment" in response.headers["content-disposition"]


async def test_export_csv_filename_reflects_date_range(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get(
        "/api/v1/export/expenses",
        params={"format": "csv", "start_date": "2025-01-01", "end_date": "2025-01-31"},
    )
    assert "2025-01-01-to-2025-01-31" in response.headers["content-disposition"]


# ── Content ───────────────────────────────────────────────────────────────


async def test_export_csv_header_row(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(response.content)
    assert rows[0] == ["Date", "Day", "Category", "Description", "Amount"]


async def test_export_csv_date_format_and_weekday(
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
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(response.content)
    assert rows[1][0] == "01-Jan-2025"
    assert rows[1][1] == "Wed"
    assert rows[1][2] == "Food"
    assert rows[1][3] == "Cake"
    assert rows[1][4] == "278.00"


async def test_export_csv_weekday_examples(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-01T00:00:00+05:30", description="A"
    )
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-02T00:00:00+05:30", description="B"
    )
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(response.content)
    assert rows[1][1] == "Wed"
    assert rows[2][1] == "Thu"


# ── Sorting ───────────────────────────────────────────────────────────────


async def test_export_csv_chronological_sorting(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-03T00:00:00+05:30", description="Third"
    )
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-01T00:00:00+05:30", description="First"
    )
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-02T00:00:00+05:30", description="Second"
    )
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(response.content)
    descriptions = [row[3] for row in rows[1:] if row]
    assert descriptions == ["First", "Second", "Third"]


# ── Filters ───────────────────────────────────────────────────────────────


async def test_export_csv_date_filters(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-01T00:00:00+05:30", description="InRange"
    )
    await create_expense(
        client, category_id=food_id, spent_at="2025-02-01T00:00:00+05:30", description="OutOfRange"
    )
    response = await client.get(
        "/api/v1/export/expenses",
        params={"format": "csv", "start_date": "2025-01-01", "end_date": "2025-01-31"},
    )
    rows = _parse_csv(response.content)
    descriptions = [row[3] for row in rows[1:] if row]
    assert descriptions == ["InRange"]


async def test_export_csv_category_filter(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    transport_id = await category_id_by_name(client, "Transport")
    await create_expense(
        client, category_id=food_id, spent_at="2025-01-01T00:00:00+05:30", description="Cake"
    )
    await create_expense(
        client, category_id=transport_id, spent_at="2025-01-02T00:00:00+05:30", description="Petrol"
    )
    response = await client.get(
        "/api/v1/export/expenses", params={"format": "csv", "category_id": food_id}
    )
    rows = _parse_csv(response.content)
    descriptions = [row[3] for row in rows[1:] if row]
    assert descriptions == ["Cake"]


# ── User isolation ────────────────────────────────────────────────────────


async def test_export_csv_user_isolation(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_b(client, email_backend)
    food_id_b = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id_b, spent_at="2025-01-01T00:00:00+05:30", description="UserB"
    )

    await login_user_a(client, email_backend)
    food_id_a = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id_a, spent_at="2025-01-01T00:00:00+05:30", description="UserA"
    )

    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(response.content)
    descriptions = [row[3] for row in rows[1:] if row]
    assert descriptions == ["UserA"]


# ── Empty export ──────────────────────────────────────────────────────────


async def test_export_csv_empty_result(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    assert response.status_code == 200
    rows = _parse_csv(response.content)
    assert rows == [["Date", "Day", "Category", "Description", "Amount"]]


# ── Format validation ─────────────────────────────────────────────────────


async def test_export_unsupported_format_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "json"})
    assert response.status_code == 422
