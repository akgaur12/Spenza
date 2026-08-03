"""Cross-account security tests for import/export: a regular user must never
be able to touch another user's data, and admin privileges grant no
implicit access to another user's expenses or categories — every operation
is always scoped to `CurrentUser`, never a client-supplied identity.
"""

import csv
import io

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import RecordingEmailBackend, promote_to_admin
from tests.import_export.helpers import (
    USER_A,
    build_csv_bytes,
    category_id_by_name,
    create_category,
    create_expense,
    login_user_a,
    login_user_b,
    preview_and_confirm,
    preview_import,
    switch_to_user_a,
    switch_to_user_b,
)


def _parse_csv(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


async def test_user_a_cannot_export_user_b_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_b(client, email_backend)
    food_id_b = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id_b, spent_at="2025-01-01T00:00:00+05:30", description="SecretB"
    )

    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(response.content)
    descriptions = [row[3] for row in rows[1:] if row]
    assert "SecretB" not in descriptions


async def test_user_a_cannot_import_using_user_b_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await login_user_b(client, email_backend)
    await create_category(client, "UserBOnly")

    await switch_to_user_a(client)
    content = build_csv_bytes([("01-Jan-2025", "UserBOnly", "Should fail", "100")])
    response = await preview_import(client, content, "expenses.csv")
    row = response.json()["data"]["rows"][0]
    assert row["valid"] is False
    assert row["errors"][0]["code"] == "CATEGORY_NOT_FOUND"


async def test_admin_export_only_covers_own_expenses(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id_a = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id_a,
        spent_at="2025-01-01T00:00:00+05:30",
        description="UserAExpense",
    )

    await promote_to_admin(db_session_factory, USER_A["email"])
    response = await client.post(
        "/api/users/login",
        json={"identifier": USER_A["email"], "password": USER_A["password"]},
    )
    assert response.status_code == 200, response.text

    # The now-admin user A still only sees their own expenses — there is no
    # endpoint or parameter that lets an admin export another user's data.
    export_response = await client.get("/api/v1/export/expenses", params={"format": "csv"})
    rows = _parse_csv(export_response.content)
    descriptions = [row[3] for row in rows[1:] if row]
    assert descriptions == ["UserAExpense"]


async def test_admin_import_creates_expenses_for_admin_only(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await login_user_b(client, email_backend)

    await promote_to_admin(db_session_factory, USER_A["email"])
    await switch_to_user_a(client)

    # The confirm endpoint never accepts a target user id — an admin's
    # import always lands on their own account, just like a regular user's.
    content = build_csv_bytes([("01-Jan-2025", "Food", "AdminExpense", "100")])
    _, confirm_response = await preview_and_confirm(client, content, "expenses.csv")
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirm_response.json()["data"]["imported_count"] == 1

    admin_listing = await client.get("/api/v1/expenses")
    assert admin_listing.json()["data"]["total"] == 1

    await switch_to_user_b(client)
    user_b_listing = await client.get("/api/v1/expenses")
    assert user_b_listing.json()["data"]["total"] == 0
