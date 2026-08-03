"""Shared test helpers for the `import_export` test package."""

import csv
import io
from collections.abc import Sequence
from typing import Any

import openpyxl
from httpx import AsyncClient, Response

from tests.conftest import RecordingEmailBackend, register_verified_user

USER_A = {"email": "user.a@example.com", "password": "SecureP@ss1"}
USER_A_SIGNUP = {**USER_A, "username": "user_a"}
USER_A_LOGIN = {"identifier": USER_A["email"], "password": USER_A["password"]}

USER_B = {"email": "user.b@example.com", "password": "SecureP@ss1"}
USER_B_SIGNUP = {**USER_B, "username": "user_b"}
USER_B_LOGIN = {"identifier": USER_B["email"], "password": USER_B["password"]}

DEFAULT_HEADER = ("Date", "Category", "Description", "Amount")


async def login_user_a(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def login_user_b(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_B_SIGNUP)
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text


async def switch_to_user_a(client: AsyncClient) -> None:
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def switch_to_user_b(client: AsyncClient) -> None:
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text


async def category_id_by_name(client: AsyncClient, name: str) -> str:
    response = await client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    category_id: str = next(i for i in items if i["name"] == name)["id"]
    return category_id


async def create_category(client: AsyncClient, name: str, icon: str | None = None) -> str:
    payload: dict[str, object] = {"name": name}
    if icon is not None:
        payload["icon"] = icon
    response = await client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201, response.text
    category_id: str = response.json()["data"]["id"]
    return category_id


async def deactivate_category(client: AsyncClient, category_id: str) -> None:
    response = await client.delete(f"/api/v1/categories/{category_id}")
    assert response.status_code == 204, response.text


async def create_expense(
    client: AsyncClient,
    *,
    category_id: str,
    spent_at: str,
    description: str = "Expense",
    amount: str = "100.00",
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


async def list_expenses(client: AsyncClient, **params: str | int) -> dict[str, Any]:
    response = await client.get("/api/v1/expenses", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def build_csv_bytes(
    rows: Sequence[tuple[str, ...]], header: tuple[str, ...] = DEFAULT_HEADER
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_xlsx_bytes(
    rows: Sequence[tuple[Any, ...]], header: tuple[str, ...] = DEFAULT_HEADER
) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def preview_import(
    client: AsyncClient,
    content: bytes,
    filename: str,
    content_type: str = "text/csv",
) -> Response:
    return await client.post(
        "/api/v1/import/expenses/preview",
        files={"file": (filename, content, content_type)},
    )


async def confirm_import(client: AsyncClient, import_token: str) -> Response:
    return await client.post("/api/v1/import/expenses/confirm", json={"import_token": import_token})


async def preview_and_confirm(
    client: AsyncClient, content: bytes, filename: str, content_type: str = "text/csv"
) -> tuple[Response, Response]:
    preview_response = await preview_import(client, content, filename, content_type)
    assert preview_response.status_code == 200, preview_response.text
    token: str = preview_response.json()["data"]["import_token"]
    confirm_response = await confirm_import(client, token)
    return preview_response, confirm_response
