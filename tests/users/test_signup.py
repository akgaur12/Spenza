"""Integration tests for POST /api/users/signup."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user


async def test_signup_creates_unverified_user_and_sends_otp(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    response = await client.post(
        "/api/users/signup",
        json={"email": "new.user@example.com", "username": "new_user", "password": "SecureP@ss1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "new.user@example.com"
    assert body["data"]["is_verified"] is False

    assert len(email_backend.sent) == 1
    assert email_backend.sent[0]["to"] == "new.user@example.com"


async def test_signup_with_full_name_persists_it(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    payload = {
        "email": "named.user@example.com",
        "username": "named_user",
        "password": "SecureP@ss1",
        "full_name": "Jane Doe",
    }
    await register_verified_user(client, email_backend, payload)
    await client.post(
        "/api/users/login",
        json={"identifier": payload["email"], "password": payload["password"]},
    )

    response = await client.get("/api/users/profile")

    assert response.status_code == 200
    assert response.json()["data"]["full_name"] == "Jane Doe"


async def test_signup_without_full_name_defaults_to_none(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/signup",
        json={"email": "noname@example.com", "username": "noname_user", "password": "SecureP@ss1"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["email"] == "noname@example.com"


async def test_signup_duplicate_verified_email_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    payload = await register_verified_user(client, email_backend)

    response = await client.post(
        "/api/users/signup",
        json={"email": payload["email"], "username": "another_name", "password": "SecureP@ss1"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "EMAIL_ALREADY_EXISTS"


async def test_signup_duplicate_username_rejected(client: AsyncClient) -> None:
    await client.post(
        "/api/users/signup",
        json={"email": "first@example.com", "username": "shared_name", "password": "SecureP@ss1"},
    )

    response = await client.post(
        "/api/users/signup",
        json={
            "email": "second@example.com",
            "username": "shared_name",
            "password": "SecureP@ss1",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "USERNAME_ALREADY_EXISTS"


async def test_signup_rejects_weak_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/signup",
        json={"email": "weak@example.com", "username": "weak_pw", "password": "alllowercase"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


async def test_signup_rejects_invalid_username(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/signup",
        json={"email": "bad@example.com", "username": "1bad", "password": "SecureP@ss1"},
    )
    assert response.status_code == 422
