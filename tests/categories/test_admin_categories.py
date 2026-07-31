"""Integration tests for the /api/v1/admin/categories endpoints."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user

ADMIN_CREDENTIALS = {"email": "admin.cat@example.com", "password": "SecureP@ss1"}
ADMIN_SIGNUP_PAYLOAD = {**ADMIN_CREDENTIALS, "username": "admin_cat_user"}
ADMIN_LOGIN_PAYLOAD = {
    "identifier": ADMIN_CREDENTIALS["email"],
    "password": ADMIN_CREDENTIALS["password"],
}

PLAIN_CREDENTIALS = {"email": "plain.cat@example.com", "password": "SecureP@ss1"}
PLAIN_SIGNUP_PAYLOAD = {**PLAIN_CREDENTIALS, "username": "plain_cat_user"}
PLAIN_LOGIN_PAYLOAD = {
    "identifier": PLAIN_CREDENTIALS["email"],
    "password": PLAIN_CREDENTIALS["password"],
}


async def _login_as_admin(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_verified_user(client, email_backend, ADMIN_SIGNUP_PAYLOAD)
    await promote_to_admin(db_session_factory, ADMIN_CREDENTIALS["email"])
    response = await client.post("/api/users/login", json=ADMIN_LOGIN_PAYLOAD)
    assert response.status_code == 200, response.text


async def _login_as_plain_user(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    response = await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)
    assert response.status_code == 200, response.text


async def _admin_find_by_name(client: AsyncClient, name: str) -> dict[str, object]:
    response = await client.get("/api/v1/admin/categories")
    assert response.status_code == 200, response.text
    items: list[dict[str, object]] = response.json()["data"]["items"]
    return next(i for i in items if i["name"] == name)


# ── Access control ────────────────────────────────────────────────────────


async def test_admin_list_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/admin/categories")
    assert response.status_code == 401


async def test_admin_list_rejects_non_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_as_plain_user(client, email_backend)

    response = await client.get("/api/v1/admin/categories")

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_normal_user_cannot_create_system_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_as_plain_user(client, email_backend)

    response = await client.post("/api/v1/admin/categories", json={"name": "Personal Care"})

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_normal_user_cannot_update_system_category_via_admin_endpoint(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    food = await _admin_find_by_name(client, "Food")

    await _login_as_plain_user(client, email_backend)
    response = await client.patch(f"/api/v1/admin/categories/{food['id']}", json={"name": "Snacks"})

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_normal_user_cannot_delete_system_category_via_admin_endpoint(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    food = await _admin_find_by_name(client, "Food")

    await _login_as_plain_user(client, email_backend)
    response = await client.delete(f"/api/v1/admin/categories/{food['id']}")

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


# ── List ──────────────────────────────────────────────────────────────────


async def test_admin_can_list_system_categories_including_inactive(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    food = await _admin_find_by_name(client, "Food")

    deactivate_response = await client.delete(f"/api/v1/admin/categories/{food['id']}")
    assert deactivate_response.status_code == 204

    active_response = await client.get("/api/v1/admin/categories", params={"is_active": "true"})
    active_names = {i["name"] for i in active_response.json()["data"]["items"]}
    assert "Food" not in active_names

    inactive_response = await client.get("/api/v1/admin/categories", params={"is_active": "false"})
    inactive_names = {i["name"] for i in inactive_response.json()["data"]["items"]}
    assert "Food" in inactive_names

    all_response = await client.get("/api/v1/admin/categories")
    all_names = {i["name"] for i in all_response.json()["data"]["items"]}
    assert "Food" in all_names


# ── Create ────────────────────────────────────────────────────────────────


async def test_admin_create_system_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    response = await client.post(
        "/api/v1/admin/categories", json={"name": "Personal Care", "icon": "🧴"}
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["name"] == "Personal Care"
    assert data["is_system"] is True
    assert data["is_active"] is True


async def test_admin_create_system_category_visible_to_normal_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await client.post("/api/v1/admin/categories", json={"name": "Personal Care", "icon": "🧴"})

    await _login_as_plain_user(client, email_backend)
    response = await client.get("/api/v1/categories")

    names = {i["name"] for i in response.json()["data"]["items"]}
    assert "Personal Care" in names


async def test_admin_create_rejects_duplicate_system_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    response = await client.post("/api/v1/admin/categories", json={"name": "FOOD"})

    assert response.status_code == 409
    assert response.json()["error_code"] == "CATEGORY_ALREADY_EXISTS"


# ── Update ────────────────────────────────────────────────────────────────


async def test_admin_can_update_system_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    food = await _admin_find_by_name(client, "Food")

    response = await client.patch(
        f"/api/v1/admin/categories/{food['id']}", json={"name": "Groceries", "icon": "🛒"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Groceries"
    assert data["icon"] == "🛒"


async def test_admin_can_deactivate_system_category_via_patch(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    food = await _admin_find_by_name(client, "Food")

    response = await client.patch(
        f"/api/v1/admin/categories/{food['id']}", json={"is_active": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["is_active"] is False


async def test_admin_update_does_not_modify_user_owned_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_plain_user(client, email_backend)
    create_response = await client.post("/api/v1/categories", json={"name": "Gym"})
    category_id = create_response.json()["data"]["id"]

    await _login_as_admin(client, email_backend, db_session_factory)
    response = await client.patch(
        f"/api/v1/admin/categories/{category_id}", json={"name": "Hijacked"}
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"


# ── Delete (deactivate) ──────────────────────────────────────────────────


async def test_admin_delete_soft_deletes_system_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    food = await _admin_find_by_name(client, "Food")

    response = await client.delete(f"/api/v1/admin/categories/{food['id']}")
    assert response.status_code == 204

    all_response = await client.get("/api/v1/admin/categories")
    food_after = next(i for i in all_response.json()["data"]["items"] if i["name"] == "Food")
    assert food_after["is_active"] is False


async def test_admin_delete_does_not_modify_user_owned_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_plain_user(client, email_backend)
    create_response = await client.post("/api/v1/categories", json={"name": "Gym"})
    category_id = create_response.json()["data"]["id"]

    await _login_as_admin(client, email_backend, db_session_factory)
    response = await client.delete(f"/api/v1/admin/categories/{category_id}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "CATEGORY_NOT_FOUND"
