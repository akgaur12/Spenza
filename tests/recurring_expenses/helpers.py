"""Shared HTTP helpers for the `recurring_expenses` test package.

User/category/expense helpers are reused directly from
`tests.import_export.helpers` rather than redefined here.
"""

from typing import Any

from httpx import AsyncClient, Response


async def create_recurring_expense(
    client: AsyncClient,
    *,
    category_id: str,
    start_date: str,
    description: str = "Netflix Subscription",
    amount: str = "649.00",
    frequency: str = "monthly",
    generation_mode: str = "auto",
    end_date: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, object] = {
        "category_id": category_id,
        "description": description,
        "amount": amount,
        "frequency": frequency,
        "generation_mode": generation_mode,
        "start_date": start_date,
    }
    if end_date is not None:
        payload["end_date"] = end_date
    response = await client.post("/api/v1/recurring-expenses", json=payload)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def get_recurring_expense(client: AsyncClient, recurring_id: str) -> Response:
    return await client.get(f"/api/v1/recurring-expenses/{recurring_id}")


async def list_recurring_expenses(client: AsyncClient, **params: str | int) -> dict[str, Any]:
    response = await client.get("/api/v1/recurring-expenses", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def update_recurring_expense(
    client: AsyncClient, recurring_id: str, payload: dict[str, object]
) -> Response:
    return await client.patch(f"/api/v1/recurring-expenses/{recurring_id}", json=payload)


async def delete_recurring_expense(client: AsyncClient, recurring_id: str) -> Response:
    return await client.delete(f"/api/v1/recurring-expenses/{recurring_id}")


async def pause_recurring_expense(client: AsyncClient, recurring_id: str) -> Response:
    return await client.patch(f"/api/v1/recurring-expenses/{recurring_id}/pause")


async def resume_recurring_expense(client: AsyncClient, recurring_id: str) -> Response:
    return await client.patch(f"/api/v1/recurring-expenses/{recurring_id}/resume")


async def run_recurring_expense(client: AsyncClient, recurring_id: str) -> Response:
    return await client.post(f"/api/v1/recurring-expenses/{recurring_id}/run")
