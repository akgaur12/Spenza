"""`health_router`: app liveness and database connectivity checks.

- `GET /health/app` — pure liveness, no dependencies (safe for a k8s
  liveness probe: a DB hiccup should never restart the pod).
- `GET /health/db` — database connectivity only (safe for a readiness
  probe / load-balancer health check).
- `GET /health` — combined report for humans/dashboards.

Any unhealthy component returns `503` so infra tooling can act on status
codes alone without parsing the body.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.core.exceptions import ServiceUnavailableError
from src.core.responses import SuccessResponse
from src.modules.health.schemas import ComponentHealth, HealthReport
from src.modules.health.service import HealthService, check_app_health

health_router = APIRouter(prefix="/health", tags=["health"])


def get_health_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> HealthService:
    return HealthService(session)


@health_router.get(
    "",
    response_model=SuccessResponse[HealthReport],
    summary="Combined app + database health",
)
async def get_health(
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> SuccessResponse[HealthReport]:
    report = await health_service.check_all()
    if report.status != "ok":
        raise ServiceUnavailableError(
            message="One or more components are unhealthy", details=report.model_dump()
        )
    return SuccessResponse(message="Healthy", data=report)


@health_router.get(
    "/app",
    response_model=SuccessResponse[ComponentHealth],
    summary="Application liveness (no external dependencies)",
)
def get_app_health() -> SuccessResponse[ComponentHealth]:
    return SuccessResponse(message="Healthy", data=check_app_health())


@health_router.get(
    "/db",
    response_model=SuccessResponse[ComponentHealth],
    summary="Database connectivity check",
)
async def get_db_health(
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> SuccessResponse[ComponentHealth]:
    component = await health_service.check_database()
    if component.status != "ok":
        raise ServiceUnavailableError(
            message="Database is unreachable", details=component.model_dump()
        )
    return SuccessResponse(message="Healthy", data=component)
