"""Integration tests for PATCH /api/users/update-profile and GET /api/users/profile."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "profile.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "profile_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_get_profile_returns_full_profile(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.get("/api/users/profile")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["email"] == CREDENTIALS["email"]
    assert "created_at" in data


async def test_update_profile_sets_full_name(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.patch("/api/users/update-profile", json={"full_name": "Jane Doe"})

    assert response.status_code == 200
    assert response.json()["data"]["full_name"] == "Jane Doe"


async def test_profile_endpoints_require_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/users/profile")).status_code == 401
    assert (
        await client.patch("/api/users/update-profile", json={"full_name": "x"})
    ).status_code == 401
