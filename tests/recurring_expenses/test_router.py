"""Integration tests for the `/api/v1/recurring-expenses` endpoints."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import (
    category_id_by_name,
    list_expenses,
    login_user_a,
    login_user_b,
    switch_to_user_a,
)
from tests.recurring_expenses.helpers import (
    create_recurring_expense,
    delete_recurring_expense,
    get_recurring_expense,
    list_recurring_expenses,
    pause_recurring_expense,
    resume_recurring_expense,
    run_recurring_expense,
    update_recurring_expense,
)


async def test_create_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/recurring-expenses",
        json={
            "category_id": "5e2f3f3a-8b8a-4b1a-9a1a-6f6a1e2c9d10",
            "description": "Netflix",
            "amount": "649.00",
            "frequency": "monthly",
            "generation_mode": "auto",
            "start_date": "2026-08-01",
        },
    )
    assert response.status_code == 401


async def test_create_returns_full_recurring_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    data = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    assert data["description"] == "Netflix Subscription"
    assert data["amount"] == "649.00"
    assert data["category"]["name"] == "Food"
    assert data["frequency"] == "monthly"
    assert data["generation_mode"] == "auto"
    assert data["status"] == "active"
    assert data["start_date"] == "2026-08-01"
    assert data["next_run_date"] == "2026-08-01"
    assert data["last_run_date"] is None


async def test_create_rejects_unknown_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post(
        "/api/v1/recurring-expenses",
        json={
            "category_id": "00000000-0000-0000-0000-000000000000",
            "description": "Netflix",
            "amount": "649.00",
            "frequency": "monthly",
            "generation_mode": "auto",
            "start_date": "2026-08-01",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_create_rejects_end_date_before_start_date(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    response = await client.post(
        "/api/v1/recurring-expenses",
        json={
            "category_id": food_id,
            "description": "Netflix",
            "amount": "649.00",
            "frequency": "monthly",
            "generation_mode": "auto",
            "start_date": "2026-08-10",
            "end_date": "2026-08-01",
        },
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_RECURRING_EXPENSE_DATE_RANGE"


async def test_create_rejects_non_positive_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    response = await client.post(
        "/api/v1/recurring-expenses",
        json={
            "category_id": food_id,
            "description": "Netflix",
            "amount": "0.00",
            "frequency": "monthly",
            "generation_mode": "auto",
            "start_date": "2026-08-01",
        },
    )
    assert response.status_code == 422


async def test_create_rejects_invalid_frequency(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    response = await client.post(
        "/api/v1/recurring-expenses",
        json={
            "category_id": food_id,
            "description": "Netflix",
            "amount": "10.00",
            "frequency": "biweekly",
            "generation_mode": "auto",
            "start_date": "2026-08-01",
        },
    )
    assert response.status_code == 422


async def test_get_own_recurring_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await get_recurring_expense(client, created["id"])
    assert response.status_code == 200
    assert response.json()["data"]["id"] == created["id"]


async def test_get_unknown_id_is_not_found(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await get_recurring_expense(client, "00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error_code"] == "RECURRING_EXPENSE_NOT_FOUND"


async def test_user_cannot_see_another_users_recurring_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    await login_user_b(client, email_backend)
    response = await get_recurring_expense(client, created["id"])
    assert response.status_code == 404


async def test_list_filters_search_sort_and_paginate(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    travel_id = await category_id_by_name(client, "Travel")

    await create_recurring_expense(
        client,
        category_id=food_id,
        description="Netflix Subscription",
        amount="649.00",
        frequency="monthly",
        generation_mode="auto",
        start_date="2026-08-01",
    )
    await create_recurring_expense(
        client,
        category_id=travel_id,
        description="Fuel budget reminder",
        amount="50.00",
        frequency="weekly",
        generation_mode="reminder",
        start_date="2026-08-01",
    )

    # Filter by generation_mode.
    data = await list_recurring_expenses(client, generation_mode="reminder")
    assert data["total"] == 1
    assert data["items"][0]["description"] == "Fuel budget reminder"

    # Filter by frequency.
    data = await list_recurring_expenses(client, frequency="monthly")
    assert data["total"] == 1
    assert data["items"][0]["description"] == "Netflix Subscription"

    # Search matches description.
    data = await list_recurring_expenses(client, search="netflix")
    assert data["total"] == 1

    # Search matches category name.
    data = await list_recurring_expenses(client, search="travel")
    assert data["total"] == 1
    assert data["items"][0]["description"] == "Fuel budget reminder"

    # Sort by amount ascending.
    data = await list_recurring_expenses(client, sort_by="amount", sort_order="asc")
    assert [i["amount"] for i in data["items"]] == ["50.00", "649.00"]

    # Pagination.
    data = await list_recurring_expenses(client, page=1, page_size=1)
    assert data["total"] == 2
    assert data["total_pages"] == 2
    assert len(data["items"]) == 1


async def test_list_only_shows_current_users_own_recurring_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    await login_user_b(client, email_backend)
    data = await list_recurring_expenses(client)
    assert data["total"] == 0


async def test_update_changes_fields(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await update_recurring_expense(
        client, created["id"], {"amount": "699.00", "description": "Netflix Premium"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["amount"] == "699.00"
    assert data["description"] == "Netflix Premium"


async def test_update_status_to_cancelled_is_allowed(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await update_recurring_expense(client, created["id"], {"status": "cancelled"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"


async def test_update_status_to_active_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await update_recurring_expense(client, created["id"], {"status": "active"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_RECURRING_EXPENSE_STATUS"


async def test_update_on_cancelled_recurring_expense_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")
    await update_recurring_expense(client, created["id"], {"status": "cancelled"})

    response = await update_recurring_expense(client, created["id"], {"amount": "1.00"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "RECURRING_EXPENSE_TERMINAL_STATE"


async def test_update_another_users_recurring_expense_is_not_found(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    await login_user_b(client, email_backend)
    response = await update_recurring_expense(client, created["id"], {"amount": "1.00"})
    assert response.status_code == 404


async def test_delete_removes_it_permanently(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await delete_recurring_expense(client, created["id"])
    assert response.status_code == 204

    response = await get_recurring_expense(client, created["id"])
    assert response.status_code == 404


async def test_pause_then_resume(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await pause_recurring_expense(client, created["id"])
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "paused"

    response = await resume_recurring_expense(client, created["id"])
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "active"


async def test_pause_twice_is_conflict(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    await pause_recurring_expense(client, created["id"])
    response = await pause_recurring_expense(client, created["id"])
    assert response.status_code == 409
    assert response.json()["error_code"] == "RECURRING_EXPENSE_NOT_ACTIVE"


async def test_resume_without_pause_is_conflict(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")

    response = await resume_recurring_expense(client, created["id"])
    assert response.status_code == 409
    assert response.json()["error_code"] == "RECURRING_EXPENSE_NOT_PAUSED"


async def test_run_generates_a_real_expense_visible_in_the_expense_list(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(
        client,
        category_id=food_id,
        description="Netflix Subscription",
        amount="649.00",
        start_date="2026-08-01",
    )

    response = await run_recurring_expense(client, created["id"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["last_run_date"] == "2026-08-01"
    assert data["next_run_date"] == "2026-09-01"

    expenses = await list_expenses(client, search="Netflix")
    assert expenses["total"] == 1
    assert expenses["items"][0]["amount"] == "649.00"


async def test_run_on_paused_recurring_expense_is_conflict(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")
    await pause_recurring_expense(client, created["id"])

    response = await run_recurring_expense(client, created["id"])
    assert response.status_code == 409
    assert response.json()["error_code"] == "RECURRING_EXPENSE_NOT_ACTIVE"


async def test_run_in_reminder_mode_never_creates_an_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(
        client,
        category_id=food_id,
        description="Rent reminder",
        amount="15000.00",
        generation_mode="reminder",
        start_date="2026-08-01",
    )

    response = await run_recurring_expense(client, created["id"])
    assert response.status_code == 200

    expenses = await list_expenses(client, search="Rent")
    assert expenses["total"] == 0


async def test_full_ownership_isolation_across_all_actions(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    created = await create_recurring_expense(client, category_id=food_id, start_date="2026-08-01")
    recurring_id = created["id"]

    await login_user_b(client, email_backend)
    assert (await get_recurring_expense(client, recurring_id)).status_code == 404
    assert (await pause_recurring_expense(client, recurring_id)).status_code == 404
    assert (await resume_recurring_expense(client, recurring_id)).status_code == 404
    assert (await run_recurring_expense(client, recurring_id)).status_code == 404
    assert (await delete_recurring_expense(client, recurring_id)).status_code == 404

    await switch_to_user_a(client)
    assert (await get_recurring_expense(client, recurring_id)).status_code == 200
