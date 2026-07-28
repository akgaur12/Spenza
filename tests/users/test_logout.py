"""Integration tests for POST /api/users/logout and /logout-all-devices."""

from httpx import ASGITransport, AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "logout.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "logout_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_logout_revokes_current_session(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    logout_resp = await client.post("/api/users/logout")
    assert logout_resp.status_code == 200

    refresh_resp = await client.post("/api/users/refresh-token")
    assert refresh_resp.status_code == 401
    assert refresh_resp.json()["error_code"] in {
        "INVALID_REFRESH_TOKEN",
        "REFRESH_TOKEN_REVOKED",
    }


async def test_logout_without_session_is_a_no_op(client: AsyncClient) -> None:
    response = await client.post("/api/users/logout")
    assert response.status_code == 200


async def test_logout_all_devices_revokes_every_session(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    from src.app import app as fastapi_app

    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as device_b:
        await device_b.post("/api/users/login", json=LOGIN_PAYLOAD)

        await client.post("/api/users/logout-all-devices")

        response = await device_b.post("/api/users/refresh-token")
        assert response.status_code == 401
        assert response.json()["error_code"] == "REFRESH_TOKEN_REVOKED"


async def test_logout_all_devices_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/users/logout-all-devices")
    assert response.status_code == 401
