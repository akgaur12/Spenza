"""Business logic for the `health` module: app liveness and DB connectivity."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.logger import get_logger
from src.modules.health.schemas import ComponentHealth, HealthReport

logger = get_logger(__name__)


def check_app_health() -> ComponentHealth:
    """The process is up and serving requests — no external dependencies.

    Deliberately takes no DB session: this is the pure liveness check, so it
    must stay true even if the database is down.
    """
    return ComponentHealth(status="ok", detail=f"{settings.APP_NAME} v{settings.APP_VERSION}")


class HealthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_database(self) -> ComponentHealth:
        """Round-trips a trivial query against Postgres to confirm connectivity."""
        try:
            await self._session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.error("health.database.unreachable", error=str(exc))
            return ComponentHealth(status="error", detail="Database is unreachable")
        return ComponentHealth(status="ok")

    async def check_all(self) -> HealthReport:
        app_health = check_app_health()
        db_health = await self.check_database()
        overall = "ok" if app_health.status == "ok" and db_health.status == "ok" else "error"
        return HealthReport(status=overall, app=app_health, database=db_health)
