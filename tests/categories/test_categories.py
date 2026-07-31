"""Integration tests for the /api/v1/categories endpoints."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.categories.models import Category
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
    """Re-authenticate as an already-registered user A (no signup)."""
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def _switch_to_user_b(client: AsyncClient) -> None:
    """Re-authenticate as an already-registered user B (no signup)."""
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text


async def _list_items(client: AsyncClient, **params: str) -> list[dict[str, object]]:
    response = await client.get("/api/v1/categories", params=params)
    assert response.status_code == 200, response.text
    items: list[dict[str, object]] = response.json()["data"]["items"]
    return items


async def _find_by_name(client: AsyncClient, name: str) -> dict[str, object]:
    items = await _list_items(client)
    return next(i for i in items if i["name"] == name)


async def _create_category(
    client: AsyncClient, name: str, icon: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name}
    if icon is not None:
        payload["icon"] = icon
    response = await client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()["data"]
    return data


# ── Default / system categories ──────────────────────────────────────────


async def test_default_categories_are_seeded_and_visible(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    items = await _list_items(client)

    names = {i["name"] for i in items}
    assert {"Food", "Transport", "Shopping", "Rent", "Bills", "Other"} <= names
    food = next(i for i in items if i["name"] == "Food")
    assert food["is_system"] is True
    assert food["icon"] == "🍔"


async def test_inactive_system_category_excluded_from_listing(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        result = await session.execute(select(Category).where(Category.name == "Food"))
        food = result.scalar_one()
        food.is_active = False
        await session.commit()

    await _login_user_a(client, email_backend)
    items = await _list_items(client)

    assert "Food" not in {i["name"] for i in items}


# ── Listing isolation ─────────────────────────────────────────────────────


async def test_list_categories_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/categories")
    assert response.status_code == 401


async def test_user_sees_system_and_own_categories_but_not_another_users(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    await _create_category(client, "Gym", "🏋️")

    await _login_user_b(client, email_backend)
    await _create_category(client, "Coffee", "☕")

    b_names = {i["name"] for i in await _list_items(client)}
    assert "Coffee" in b_names
    assert "Food" in b_names
    assert "Gym" not in b_names

    await _switch_to_user_a(client)
    a_names = {i["name"] for i in await _list_items(client)}
    assert "Gym" in a_names
    assert "Coffee" not in a_names


async def test_search_is_case_insensitive(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    items = await _list_items(client, search="FOOD")

    assert [i["name"] for i in items] == ["Food"]


# ── Create ────────────────────────────────────────────────────────────────


async def test_create_category_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/categories", json={"name": "Gym"})
    assert response.status_code == 401


async def test_create_category_success(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    data = await _create_category(client, "Gym", "🏋️")

    assert data["name"] == "Gym"
    assert data["icon"] == "🏋️"
    assert data["is_system"] is False
    assert data["is_active"] is True
    assert "created_at" in data
    assert "updated_at" in data
    assert "user_id" not in data


async def test_create_category_ignores_client_supplied_ownership_fields(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    me_response = await client.get("/api/users/me")
    user_a_id = me_response.json()["data"]["id"]

    await _login_user_b(client, email_backend)
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Injected",
            "user_id": user_a_id,
            "is_system": True,
            "is_active": False,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["is_system"] is False

    b_names = {i["name"] for i in await _list_items(client)}
    assert "Injected" in b_names

    await _switch_to_user_a(client)
    a_names = {i["name"] for i in await _list_items(client)}
    assert "Injected" not in a_names


async def test_create_category_rejects_empty_name(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    response = await client.post("/api/v1/categories", json={"name": ""})
    assert response.status_code == 422


async def test_create_category_rejects_whitespace_only_name(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    response = await client.post("/api/v1/categories", json={"name": "   "})
    assert response.status_code == 422


async def test_create_category_rejects_duplicate_name(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    await _create_category(client, "Gym")

    response = await client.post("/api/v1/categories", json={"name": "Gym"})

    assert response.status_code == 409
    assert response.json()["error_code"] == "CATEGORY_ALREADY_EXISTS"


async def test_create_category_rejects_case_insensitive_duplicate(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    await _create_category(client, "Gym")

    response = await client.post("/api/v1/categories", json={"name": "  GYM  "})

    assert response.status_code == 409
    assert response.json()["error_code"] == "CATEGORY_ALREADY_EXISTS"


async def test_create_category_allows_same_name_for_different_users(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    await _create_category(client, "Gym")

    await _login_user_b(client, email_backend)
    response = await client.post("/api/v1/categories", json={"name": "Gym"})

    assert response.status_code == 201, response.text


# ── Get ───────────────────────────────────────────────────────────────────


async def test_get_system_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food = await _find_by_name(client, "Food")

    response = await client.get(f"/api/v1/categories/{food['id']}")

    assert response.status_code == 200
    assert response.json()["data"]["is_system"] is True


async def test_get_own_category(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    response = await client.get(f"/api/v1/categories/{created['id']}")

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Gym"


async def test_get_another_users_category_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    await _login_user_b(client, email_backend)
    response = await client.get(f"/api/v1/categories/{created['id']}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_get_nonexistent_category_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    response = await client.get("/api/v1/categories/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


# ── Update ────────────────────────────────────────────────────────────────


async def test_update_own_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    response = await client.patch(
        f"/api/v1/categories/{created['id']}", json={"name": "Fitness", "icon": "💪"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Fitness"
    assert data["icon"] == "💪"


async def test_update_system_category_forbidden(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food = await _find_by_name(client, "Food")

    response = await client.patch(f"/api/v1/categories/{food['id']}", json={"name": "Snacks"})

    assert response.status_code == 403
    assert response.json()["error_code"] == "SYSTEM_CATEGORY_READ_ONLY"


async def test_update_another_users_category_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    await _login_user_b(client, email_backend)
    response = await client.patch(f"/api/v1/categories/{created['id']}", json={"name": "Hacked"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_update_rejects_duplicate_rename(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    await _create_category(client, "Gym")
    coffee = await _create_category(client, "Coffee")

    response = await client.patch(f"/api/v1/categories/{coffee['id']}", json={"name": "gym"})

    assert response.status_code == 409
    assert response.json()["error_code"] == "CATEGORY_ALREADY_EXISTS"


async def test_update_own_category_case_only_rename_allowed(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    response = await client.patch(f"/api/v1/categories/{created['id']}", json={"name": "GYM"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == "GYM"


# ── Delete ────────────────────────────────────────────────────────────────


async def test_delete_own_category_soft_deletes_and_hides_from_listing(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    delete_response = await client.delete(f"/api/v1/categories/{created['id']}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/categories/{created['id']}")
    assert get_response.status_code == 404

    names = {i["name"] for i in await _list_items(client)}
    assert "Gym" not in names


async def test_delete_system_category_forbidden(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food = await _find_by_name(client, "Food")

    response = await client.delete(f"/api/v1/categories/{food['id']}")

    assert response.status_code == 403
    assert response.json()["error_code"] == "SYSTEM_CATEGORY_READ_ONLY"


async def test_delete_another_users_category_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    created = await _create_category(client, "Gym")

    await _login_user_b(client, email_backend)
    response = await client.delete(f"/api/v1/categories/{created['id']}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"
