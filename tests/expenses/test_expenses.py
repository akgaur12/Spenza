"""Integration tests for the /api/v1/expenses endpoints."""

import uuid
from datetime import datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.categories.models import Category
from src.modules.expenses.models import Expense
from tests.conftest import RecordingEmailBackend, register_verified_user

USER_A = {"email": "user.a@example.com", "password": "SecureP@ss1"}
USER_A_SIGNUP = {**USER_A, "username": "user_a"}
USER_A_LOGIN = {"identifier": USER_A["email"], "password": USER_A["password"]}

USER_B = {"email": "user.b@example.com", "password": "SecureP@ss1"}
USER_B_SIGNUP = {**USER_B, "username": "user_b"}
USER_B_LOGIN = {"identifier": USER_B["email"], "password": USER_B["password"]}


async def _login_user_a(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def _login_user_b(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_B_SIGNUP)
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text


async def _switch_to_user_a(client: AsyncClient) -> None:
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def _category_id_by_name(client: AsyncClient, name: str) -> str:
    response = await client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    category_id: str = next(i for i in items if i["name"] == name)["id"]
    return category_id


async def _create_category(client: AsyncClient, name: str, icon: str | None = None) -> str:
    payload: dict[str, object] = {"name": name}
    if icon is not None:
        payload["icon"] = icon
    response = await client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201, response.text
    category_id: str = response.json()["data"]["id"]
    return category_id


async def _create_expense(
    client: AsyncClient,
    *,
    category_id: str,
    description: str = "Cake",
    amount: str = "278.00",
    spent_at: str = "2025-01-01T00:00:00+05:30",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": category_id,
            "description": description,
            "amount": amount,
            "spent_at": spent_at,
        },
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _list_expenses(client: AsyncClient, **params: str | int | list[str]) -> dict[str, Any]:
    response = await client.get("/api/v1/expenses", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


# ── Create ────────────────────────────────────────────────────────────────


async def test_create_expense_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": str(uuid.uuid4()),
            "description": "Cake",
            "amount": "278.00",
            "spent_at": "2025-01-01T00:00:00+05:30",
        },
    )
    assert response.status_code == 401


async def test_create_expense_with_system_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    data = await _create_expense(client, category_id=food_id)

    assert data["description"] == "Cake"
    assert data["amount"] == "278.00"
    assert data["category"]["id"] == food_id
    assert data["category"]["name"] == "Food"


async def test_create_expense_with_own_custom_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    gym_id = await _create_category(client, "Gym", "🏋️")

    data = await _create_expense(client, category_id=gym_id, description="Monthly membership")

    assert data["category"]["id"] == gym_id


async def test_create_expense_user_id_comes_from_authenticated_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    """`user_id` is never accepted from the client — the created expense is
    only ever visible to whoever is actually authenticated.
    """
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)
    assert "user_id" not in created

    await _login_user_b(client, email_backend)
    listing = await _list_expenses(client)
    assert listing["items"] == []


async def test_create_expense_rejects_another_users_custom_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    gym_id = await _create_category(client, "Gym")

    await _login_user_b(client, email_backend)
    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": gym_id,
            "description": "Hacked",
            "amount": "100.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_create_expense_rejects_inactive_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_user_a(client, email_backend)
    gym_id = await _create_category(client, "Gym")

    async with db_session_factory() as session:
        result = await session.execute(select(Category).where(Category.id == uuid.UUID(gym_id)))
        category = result.scalar_one()
        category.is_active = False
        await session.commit()

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": gym_id,
            "description": "Should fail",
            "amount": "100.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_create_expense_rejects_nonexistent_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": str(uuid.uuid4()),
            "description": "Ghost",
            "amount": "100.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_create_expense_rejects_zero_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": food_id,
            "description": "Free",
            "amount": "0",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 422


async def test_create_expense_rejects_negative_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": food_id,
            "description": "Refund?",
            "amount": "-10.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 422


async def test_create_expense_accepts_valid_decimal_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    data = await _create_expense(client, category_id=food_id, amount="999999.99")

    assert data["amount"] == "999999.99"


async def test_create_expense_rejects_empty_description(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": food_id,
            "description": "",
            "amount": "10.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 422


async def test_create_expense_rejects_whitespace_only_description(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": food_id,
            "description": "   ",
            "amount": "10.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 422


async def test_create_expense_trims_description(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    data = await _create_expense(client, category_id=food_id, description="  Cake  ")

    assert data["description"] == "Cake"


async def test_create_expense_rejects_description_over_255_chars(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": food_id,
            "description": "x" * 256,
            "amount": "10.00",
            "spent_at": "2025-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 422


async def test_create_expense_stores_spent_at_correctly(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")

    data = await _create_expense(client, category_id=food_id, spent_at="2025-01-01T00:00:00+05:30")

    expected = datetime.fromisoformat("2025-01-01T00:00:00+05:30")
    actual = datetime.fromisoformat(str(data["spent_at"]))
    assert actual == expected
    assert "created_at" in data
    assert "updated_at" in data


# ── List ──────────────────────────────────────────────────────────────────


async def test_list_expenses_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/expenses")
    assert response.status_code == 401


async def test_list_expenses_returns_empty_list(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    listing = await _list_expenses(client)

    assert listing == {"items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0}


async def test_list_expenses_only_returns_own_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, description="A's expense")

    await _login_user_b(client, email_backend)
    listing = await _list_expenses(client)

    assert listing["items"] == []


async def test_list_expenses_default_sort_is_newest_spending_first(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(
        client, category_id=food_id, description="Oldest", spent_at="2025-01-01T00:00:00+00:00"
    )
    await _create_expense(
        client, category_id=food_id, description="Newest", spent_at="2025-06-01T00:00:00+00:00"
    )
    await _create_expense(
        client, category_id=food_id, description="Middle", spent_at="2025-03-01T00:00:00+00:00"
    )

    listing = await _list_expenses(client)

    descriptions = [item["description"] for item in listing["items"]]
    assert descriptions == ["Newest", "Middle", "Oldest"]


async def test_list_expenses_pagination(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    for i in range(3):
        await _create_expense(
            client,
            category_id=food_id,
            description=f"Expense {i}",
            spent_at=f"2025-01-0{i + 1}T00:00:00+00:00",
        )

    page1 = await _list_expenses(client, page=1, page_size=2)
    assert len(page1["items"]) == 2
    assert page1["total"] == 3
    assert page1["total_pages"] == 2
    assert page1["page"] == 1

    page2 = await _list_expenses(client, page=2, page_size=2)
    assert len(page2["items"]) == 1
    assert page2["page"] == 2


# ── Filters ───────────────────────────────────────────────────────────────


async def test_filter_by_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    transport_id = await _category_id_by_name(client, "Transport")
    await _create_expense(client, category_id=food_id, description="Lunch")
    await _create_expense(client, category_id=transport_id, description="Uber")

    listing = await _list_expenses(client, category_id=food_id)

    assert [item["description"] for item in listing["items"]] == ["Lunch"]


async def test_filter_by_multiple_categories(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    transport_id = await _category_id_by_name(client, "Transport")
    rent_id = await _category_id_by_name(client, "Rent")
    await _create_expense(client, category_id=food_id, description="Lunch")
    await _create_expense(client, category_id=transport_id, description="Uber")
    await _create_expense(client, category_id=rent_id, description="Rent")

    listing = await _list_expenses(client, category_id=[food_id, transport_id])

    assert {item["description"] for item in listing["items"]} == {"Lunch", "Uber"}


async def test_filter_by_start_date(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(
        client, category_id=food_id, description="Before", spent_at="2026-06-30T12:00:00+00:00"
    )
    await _create_expense(
        client, category_id=food_id, description="After", spent_at="2026-07-05T12:00:00+00:00"
    )

    listing = await _list_expenses(client, start_date="2026-07-01")

    assert [item["description"] for item in listing["items"]] == ["After"]


async def test_filter_by_end_date(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(
        client, category_id=food_id, description="Within", spent_at="2026-07-15T12:00:00+00:00"
    )
    await _create_expense(
        client, category_id=food_id, description="After", spent_at="2026-08-01T12:00:00+00:00"
    )

    listing = await _list_expenses(client, end_date="2026-07-31")

    assert [item["description"] for item in listing["items"]] == ["Within"]


async def test_filter_end_date_includes_the_full_day(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(
        client,
        category_id=food_id,
        description="Late on end date",
        spent_at="2026-07-31T23:59:59+00:00",
    )

    listing = await _list_expenses(client, end_date="2026-07-31")

    assert [item["description"] for item in listing["items"]] == ["Late on end date"]


async def test_filter_by_date_range(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(
        client, category_id=food_id, description="Before", spent_at="2026-06-15T00:00:00+00:00"
    )
    await _create_expense(
        client, category_id=food_id, description="Within", spent_at="2026-07-15T00:00:00+00:00"
    )
    await _create_expense(
        client, category_id=food_id, description="After", spent_at="2026-08-15T00:00:00+00:00"
    )

    listing = await _list_expenses(client, start_date="2026-07-01", end_date="2026-07-31")

    assert [item["description"] for item in listing["items"]] == ["Within"]


async def test_filter_by_min_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, description="Cheap", amount="50.00")
    await _create_expense(client, category_id=food_id, description="Expensive", amount="500.00")

    listing = await _list_expenses(client, min_amount="100")

    assert [item["description"] for item in listing["items"]] == ["Expensive"]


async def test_filter_by_max_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, description="Cheap", amount="50.00")
    await _create_expense(client, category_id=food_id, description="Expensive", amount="500.00")

    listing = await _list_expenses(client, max_amount="100")

    assert [item["description"] for item in listing["items"]] == ["Cheap"]


async def test_filter_by_description_search(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, description="Birthday Cake")
    await _create_expense(client, category_id=food_id, description="Coffee")

    listing = await _list_expenses(client, search="cake")

    assert [item["description"] for item in listing["items"]] == ["Birthday Cake"]


async def test_filter_search_is_case_insensitive(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, description="Birthday Cake")

    listing = await _list_expenses(client, search="CAKE")

    assert [item["description"] for item in listing["items"]] == ["Birthday Cake"]


async def test_combined_filters(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    transport_id = await _category_id_by_name(client, "Transport")
    await _create_expense(
        client,
        category_id=food_id,
        description="Lunch special",
        amount="150.00",
        spent_at="2026-07-15T00:00:00+00:00",
    )
    await _create_expense(
        client,
        category_id=food_id,
        description="Lunch cheap",
        amount="50.00",
        spent_at="2026-07-15T00:00:00+00:00",
    )
    await _create_expense(
        client,
        category_id=transport_id,
        description="Lunch commute",
        amount="150.00",
        spent_at="2026-07-15T00:00:00+00:00",
    )
    await _create_expense(
        client,
        category_id=food_id,
        description="Lunch out of range",
        amount="150.00",
        spent_at="2026-06-01T00:00:00+00:00",
    )

    listing = await _list_expenses(
        client,
        category_id=food_id,
        start_date="2026-07-01",
        end_date="2026-07-31",
        min_amount="100",
        search="lunch",
    )

    assert [item["description"] for item in listing["items"]] == ["Lunch special"]


# ── Get ───────────────────────────────────────────────────────────────────


async def test_get_own_expense(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    response = await client.get(f"/api/v1/expenses/{created['id']}")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == created["id"]


async def test_get_another_users_expense_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    await _login_user_b(client, email_backend)
    response = await client.get(f"/api/v1/expenses/{created['id']}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "EXPENSE_NOT_FOUND"


async def test_get_nonexistent_expense_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    response = await client.get(f"/api/v1/expenses/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "EXPENSE_NOT_FOUND"


# ── Update ────────────────────────────────────────────────────────────────


async def test_update_own_expense_description(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id, description="Cake")

    response = await client.patch(
        f"/api/v1/expenses/{created['id']}", json={"description": "Birthday Cake"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["description"] == "Birthday Cake"


async def test_update_own_expense_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id, amount="278.00")

    response = await client.patch(f"/api/v1/expenses/{created['id']}", json={"amount": "300.00"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["amount"] == "300.00"


async def test_update_own_expense_date(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    response = await client.patch(
        f"/api/v1/expenses/{created['id']}", json={"spent_at": "2026-02-02T00:00:00+00:00"}
    )

    assert response.status_code == 200, response.text
    actual = datetime.fromisoformat(str(response.json()["data"]["spent_at"]))
    assert actual == datetime.fromisoformat("2026-02-02T00:00:00+00:00")


async def test_update_own_expense_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    transport_id = await _category_id_by_name(client, "Transport")
    created = await _create_expense(client, category_id=food_id)

    response = await client.patch(
        f"/api/v1/expenses/{created['id']}", json={"category_id": transport_id}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["category"]["id"] == transport_id


async def test_update_expense_revalidates_category_ownership(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    response = await client.patch(
        f"/api/v1/expenses/{created['id']}", json={"category_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_update_expense_rejects_another_users_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    await _login_user_b(client, email_backend)
    gym_id = await _create_category(client, "Gym")

    await _switch_to_user_a(client)
    response = await client.patch(f"/api/v1/expenses/{created['id']}", json={"category_id": gym_id})

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_update_another_users_expense_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    await _login_user_b(client, email_backend)
    response = await client.patch(
        f"/api/v1/expenses/{created['id']}", json={"description": "Hacked"}
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "EXPENSE_NOT_FOUND"


async def test_update_expense_rejects_invalid_amount(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    response = await client.patch(f"/api/v1/expenses/{created['id']}", json={"amount": "-5.00"})

    assert response.status_code == 422


# ── Delete ────────────────────────────────────────────────────────────────


async def test_delete_own_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    response = await client.delete(f"/api/v1/expenses/{created['id']}")

    assert response.status_code == 204


async def test_delete_expense_actually_removes_record(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    await client.delete(f"/api/v1/expenses/{created['id']}")

    async with db_session_factory() as session:
        result = await session.execute(
            select(Expense).where(Expense.id == uuid.UUID(str(created["id"])))
        )
        assert result.scalar_one_or_none() is None


async def test_delete_another_users_expense_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    created = await _create_expense(client, category_id=food_id)

    await _login_user_b(client, email_backend)
    response = await client.delete(f"/api/v1/expenses/{created['id']}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "EXPENSE_NOT_FOUND"


async def test_delete_nonexistent_expense_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    response = await client.delete(f"/api/v1/expenses/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "EXPENSE_NOT_FOUND"
