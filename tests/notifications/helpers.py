"""Shared HTTP helpers for the `notifications` test package.

User helpers are reused directly from `tests.import_export.helpers` rather
than redefined here.
"""

from typing import Any

from httpx import AsyncClient, Response


async def list_notifications(client: AsyncClient, **params: str | int) -> dict[str, Any]:
    response = await client.get("/api/v1/notifications", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def get_unread_count(client: AsyncClient) -> int:
    response = await client.get("/api/v1/notifications/unread-count")
    assert response.status_code == 200, response.text
    count: int = response.json()["data"]["count"]
    return count


async def mark_notification_read(client: AsyncClient, notification_id: str) -> Response:
    return await client.patch(f"/api/v1/notifications/{notification_id}/read")


async def mark_all_notifications_read(client: AsyncClient) -> Response:
    return await client.patch("/api/v1/notifications/read-all")


async def delete_notification(client: AsyncClient, notification_id: str) -> Response:
    return await client.delete(f"/api/v1/notifications/{notification_id}")


async def list_notification_preferences(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/v1/notification-preferences")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def update_notification_preference(
    client: AsyncClient, notification_type: str, payload: dict[str, object]
) -> Response:
    return await client.patch(f"/api/v1/notification-preferences/{notification_type}", json=payload)
