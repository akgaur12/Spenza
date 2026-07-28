"""Integration tests for the health module."""

import pytest
from httpx import AsyncClient

from src.modules.health.schemas import ComponentHealth
from src.modules.health.service import HealthService


async def test_app_health_is_always_ok_and_has_no_db_dependency(client: AsyncClient) -> None:
    response = await client.get("/health/app")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


async def test_db_health_ok_when_database_reachable(client: AsyncClient) -> None:
    response = await client.get("/health/db")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


async def test_combined_health_ok_when_everything_healthy(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "ok"
    assert body["app"]["status"] == "ok"
    assert body["database"]["status"] == "ok"


async def test_db_health_returns_503_when_database_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken_check_database(self: HealthService) -> ComponentHealth:
        return ComponentHealth(status="error", detail="Database is unreachable")

    monkeypatch.setattr(HealthService, "check_database", _broken_check_database)

    response = await client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_UNAVAILABLE"


async def test_combined_health_returns_503_when_database_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken_check_database(self: HealthService) -> ComponentHealth:
        return ComponentHealth(status="error", detail="Database is unreachable")

    monkeypatch.setattr(HealthService, "check_database", _broken_check_database)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_UNAVAILABLE"
