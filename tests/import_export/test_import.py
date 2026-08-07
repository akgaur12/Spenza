"""Integration tests for the /api/v1/import/expenses endpoints."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.import_export.models import ImportSession
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import (
    build_csv_bytes,
    build_xlsx_bytes,
    category_id_by_name,
    confirm_import,
    create_category,
    create_expense,
    deactivate_category,
    list_expenses,
    login_user_a,
    login_user_b,
    preview_and_confirm,
    preview_import,
    switch_to_user_a,
)

VALID_CSV_ROWS = [
    ("01-Jan-2025", "Food", "Cake", "278"),
    ("02-Jan-2025", "Transport", "Petrol", "2000"),
]


# ── Auth ──────────────────────────────────────────────────────────────────


async def test_preview_requires_authentication(client: AsyncClient) -> None:
    response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    assert response.status_code == 401


async def test_confirm_requires_authentication(client: AsyncClient) -> None:
    response = await confirm_import(client, "not-a-real-token")
    assert response.status_code == 401


# ── File type handling ───────────────────────────────────────────────────


async def test_csv_accepted(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["file_type"] == "csv"


async def test_xlsx_accepted(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(
        client,
        build_xlsx_bytes(VALID_CSV_ROWS),
        "expenses.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["file_type"] == "xlsx"


async def test_pdf_rejected_for_import(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(client, b"%PDF-1.4 fake", "expenses.pdf", "application/pdf")
    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


async def test_unsupported_extension_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(client, b"whatever", "expenses.txt", "text/plain")
    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


async def test_xls_extension_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(client, b"whatever", "expenses.xls", "application/vnd.ms-excel")
    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


# ── Header handling ───────────────────────────────────────────────────────


async def test_missing_required_columns_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes(
        [("01-Jan-2025", "Cake", "278")], header=("Date", "Description", "Amount")
    )
    response = await preview_import(client, content, "expenses.csv")
    assert response.status_code == 400
    assert response.json()["error_code"] == "IMPORT_MISSING_COLUMNS"
    assert "category" in response.json()["details"]["missing_columns"]


async def test_case_insensitive_headers_work(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes(
        [("01-Jan-2025", "Food", "Cake", "278")],
        header=("DATE", "category", "Description", "AMOUNT"),
    )
    response = await preview_import(client, content, "expenses.csv")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["valid_rows"] == 1


async def test_whitespace_around_headers_handled(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes(
        [("01-Jan-2025", "Food", "Cake", "278")],
        header=(" Date ", " Category", "Description ", " Amount "),
    )
    response = await preview_import(client, content, "expenses.csv")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["valid_rows"] == 1


async def test_extra_columns_are_ignored(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes(
        [("01-Jan-2025", "Food", "Cake", "278", "Wed")],
        header=("Date", "Category", "Description", "Amount", "Day"),
    )
    response = await preview_import(client, content, "expenses.csv")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["valid_rows"] == 1


async def test_empty_file_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([])
    response = await preview_import(client, content, "expenses.csv")
    assert response.status_code == 400
    assert response.json()["error_code"] == "IMPORT_FILE_EMPTY"


# ── Date parsing ──────────────────────────────────────────────────────────


async def test_valid_dates_parsed(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    rows = response.json()["data"]["rows"]
    assert rows[0]["date"] == "2025-01-01"
    assert rows[1]["date"] == "2025-01-02"


async def test_invalid_dates_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes(
        [
            ("31-Feb-2025", "Food", "Cake", "278"),
            ("abc", "Food", "Cake", "278"),
            ("2025-99-99", "Food", "Cake", "278"),
        ]
    )
    response = await preview_import(client, content, "expenses.csv")
    data = response.json()["data"]
    assert data["valid_rows"] == 0
    assert data["invalid_rows"] == 3
    for row in data["rows"]:
        codes = [e["code"] for e in row["errors"]]
        assert "INVALID_DATE" in codes


async def test_excel_native_dates_handled(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_xlsx_bytes([(date(2025, 1, 1), "Food", "Cake", 278)])
    response = await preview_import(
        client,
        content,
        "expenses.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    data = response.json()["data"]
    assert data["valid_rows"] == 1
    assert data["rows"][0]["date"] == "2025-01-01"


# ── Category resolution ───────────────────────────────────────────────────


async def test_valid_category_resolved(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert row["category"]["id"] == food_id
    assert row["category"]["name"] == "Food"


async def test_case_insensitive_category_matching(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", " food ", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert row["category"]["name"] == "Food"


async def test_own_personal_category_works(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await create_category(client, "Gym")
    content = build_csv_bytes([("01-Jan-2025", "Gym", "Membership", "1500")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert row["category"]["name"] == "Gym"


async def test_another_users_category_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await login_user_b(client, email_backend)
    await create_category(client, "Gaming")

    await switch_to_user_a(client)
    content = build_csv_bytes([("01-Jan-2025", "Gaming", "Console", "5000")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "CATEGORY_NOT_FOUND"


async def test_inactive_category_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    category_id = await create_category(client, "Hobby")
    await deactivate_category(client, category_id)

    content = build_csv_bytes([("01-Jan-2025", "Hobby", "Paint", "500")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "CATEGORY_INACTIVE"


async def test_missing_category_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Gaming", "Console", "5000")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "CATEGORY_NOT_FOUND"


async def test_ambiguous_category_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await create_category(client, "Food")  # collides with the system "Food" category

    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "CATEGORY_AMBIGUOUS"


# ── Description validation ───────────────────────────────────────────────


async def test_valid_description_accepted(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Monthly gym membership", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert row["description"] == "Monthly gym membership"


async def test_empty_description_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "   ", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "DESCRIPTION_REQUIRED"


async def test_description_too_long_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "x" * 256, "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "DESCRIPTION_TOO_LONG"


# ── Amount validation ─────────────────────────────────────────────────────


async def test_valid_amount_accepted(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert Decimal(row["amount"]) == Decimal("278")


async def test_decimal_precision_preserved(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "1,250.50")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert Decimal(row["amount"]) == Decimal("1250.50")


async def test_rupee_amount_parsing_works(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "₹278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert Decimal(row["amount"]) == Decimal("278")


async def test_rupee_amount_with_space_and_commas(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "₹ 1,250.50")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert Decimal(row["amount"]) == Decimal("1250.50")


async def test_zero_amount_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "0")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "AMOUNT_MUST_BE_POSITIVE"


async def test_negative_amount_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "-100")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "INVALID_AMOUNT"


async def test_invalid_amount_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "abc")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "INVALID_AMOUNT"


# ── Duplicate detection ───────────────────────────────────────────────────


async def test_row_matching_an_existing_expense_is_rejected_as_duplicate(
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

    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    data = response.json()["data"]
    row = data["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "DUPLICATE_EXPENSE"
    assert data["valid_rows"] == 0
    assert data["invalid_rows"] == 1


async def test_duplicate_row_is_excluded_from_confirmation(
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

    content = build_csv_bytes(
        [
            ("01-Jan-2025", "Food", "Cake", "278"),  # duplicate of the existing expense
            ("02-Jan-2025", "Transport", "Petrol", "2000"),  # genuinely new
        ]
    )
    preview_response = await preview_import(client, content, "expenses.csv")
    assert preview_response.json()["data"]["valid_rows"] == 1
    token = preview_response.json()["data"]["import_token"]

    confirm_response = await confirm_import(client, token)
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirm_response.json()["data"]["imported_count"] == 1

    listing = await list_expenses(client)
    assert listing["total"] == 2  # the original expense + the one new import


async def test_different_amount_is_not_flagged_as_duplicate(
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

    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "279")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True


async def test_different_description_is_not_flagged_as_duplicate(
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

    content = build_csv_bytes([("01-Jan-2025", "Food", "Different item", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True


async def test_duplicate_check_is_scoped_to_the_authenticated_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_b(client, email_backend)
    food_id_b = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id_b,
        description="Cake",
        amount="278.00",
        spent_at="2025-01-01T00:00:00+05:30",
    )

    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "Food", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True


# ── Preview semantics ─────────────────────────────────────────────────────


async def test_preview_does_not_insert_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    listing = await list_expenses(client)
    assert listing["total"] == 0


async def test_correct_valid_invalid_counts(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes(
        [
            ("01-Jan-2025", "Food", "Cake", "278"),
            ("02-Jan-2025", "Gaming", "Console", "500"),
            ("03-Jan-2025", "Entertainment", "Netflix", "649"),
        ]
    )
    response = await preview_import(client, content, "expenses.csv")
    data = response.json()["data"]
    assert data["total_rows"] == 3
    assert data["valid_rows"] == 2
    assert data["invalid_rows"] == 1


async def test_row_numbers_correspond_to_source_file(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    rows = response.json()["data"]["rows"]
    assert rows[0]["row_number"] == 2
    assert rows[1]["row_number"] == 3


# ── Confirmation ──────────────────────────────────────────────────────────


async def test_confirm_inserts_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    _, confirm_response = await preview_and_confirm(
        client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv"
    )
    assert confirm_response.status_code == 200, confirm_response.text
    result = confirm_response.json()["data"]
    assert result["status"] == "completed"
    assert result["imported_count"] == 2
    assert result["failed_count"] == 0

    listing = await list_expenses(client)
    assert listing["total"] == 2


async def test_imported_expenses_belong_to_authenticated_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await preview_and_confirm(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")

    await login_user_b(client, email_backend)
    listing = await list_expenses(client)
    assert listing["total"] == 0


async def test_same_confirmation_session_cannot_be_committed_twice(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    preview_response, first_confirm = await preview_and_confirm(
        client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv"
    )
    assert first_confirm.status_code == 200

    token = preview_response.json()["data"]["import_token"]
    second_confirm = await confirm_import(client, token)
    assert second_confirm.status_code == 409
    assert second_confirm.json()["error_code"] == "IMPORT_SESSION_ALREADY_CONFIRMED"

    listing = await list_expenses(client)
    assert listing["total"] == 2


async def test_confirm_is_transactional_on_category_invalidated_after_preview(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    category_id = await create_category(client, "Hobby")
    content = build_csv_bytes(
        [
            ("01-Jan-2025", "Hobby", "Paint", "500"),
            ("02-Jan-2025", "Hobby", "Brushes", "200"),
        ]
    )
    preview_response = await preview_import(client, content, "expenses.csv")
    assert preview_response.json()["data"]["valid_rows"] == 2
    token = preview_response.json()["data"]["import_token"]

    await deactivate_category(client, category_id)

    confirm_response = await confirm_import(client, token)
    assert confirm_response.status_code == 409
    assert confirm_response.json()["error_code"] == "IMPORT_CONFIRMATION_FAILED"

    listing = await list_expenses(client)
    assert listing["total"] == 0


async def test_confirm_with_no_valid_rows_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("31-Feb-2025", "Food", "Cake", "278")])
    preview_response = await preview_import(client, content, "expenses.csv")
    token = preview_response.json()["data"]["import_token"]

    confirm_response = await confirm_import(client, token)
    assert confirm_response.status_code == 400
    assert confirm_response.json()["error_code"] == "IMPORT_NO_VALID_ROWS"


async def test_confirm_with_invalid_token_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await confirm_import(client, "not-a-real-token")
    assert response.status_code == 404
    assert response.json()["error_code"] == "IMPORT_SESSION_NOT_FOUND"


# ── Limits ────────────────────────────────────────────────────────────────


async def test_oversized_file_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.core.app_config import settings

    monkeypatch.setattr(settings, "MAX_IMPORT_FILE_SIZE_BYTES", 10)
    await login_user_a(client, email_backend)
    response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    assert response.status_code == 400
    assert response.json()["error_code"] == "IMPORT_FILE_TOO_LARGE"


async def test_row_limit_enforced(
    client: AsyncClient, email_backend: RecordingEmailBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.core.app_config import settings

    monkeypatch.setattr(settings, "MAX_IMPORT_ROWS", 1)
    await login_user_a(client, email_backend)
    response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    assert response.status_code == 400
    assert response.json()["error_code"] == "IMPORT_ROW_LIMIT_EXCEEDED"


# ── CSV parsing details ───────────────────────────────────────────────────


async def test_quoted_csv_values_with_embedded_commas(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = (
        b'Date,Category,Description,Amount\r\n01-Jan-2025,Food,"Dinner, coffee and dessert",850\r\n'
    )
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is True
    assert row["description"] == "Dinner, coffee and dessert"


async def test_utf8_bom_handled(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    content = b"\xef\xbb\xbf" + build_csv_bytes(VALID_CSV_ROWS)
    response = await preview_import(client, content, "expenses.csv")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["valid_rows"] == 2


# ── Additional edge cases ─────────────────────────────────────────────────


async def test_blank_category_cell_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    content = build_csv_bytes([("01-Jan-2025", "", "Cake", "278")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "CATEGORY_NOT_FOUND"


async def test_confirm_with_another_users_token_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    preview_response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    token = preview_response.json()["data"]["import_token"]

    await login_user_b(client, email_backend)
    response = await confirm_import(client, token)
    assert response.status_code == 404
    assert response.json()["error_code"] == "IMPORT_SESSION_NOT_FOUND"

    listing = await list_expenses(client)
    assert listing["total"] == 0


async def test_confirm_rejects_a_genuinely_expired_session(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    preview_response = await preview_import(client, build_csv_bytes(VALID_CSV_ROWS), "expenses.csv")
    token = preview_response.json()["data"]["import_token"]

    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email("user.a@example.com")
        assert user is not None
        result = await session.execute(
            select(ImportSession).where(ImportSession.user_id == user.id)
        )
        import_session = result.scalar_one()
        import_session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    response = await confirm_import(client, token)
    assert response.status_code == 422
    assert response.json()["error_code"] == "IMPORT_SESSION_EXPIRED"
