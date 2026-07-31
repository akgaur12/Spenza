"""FastAPI dependency providers for the `dashboard` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.dashboard.service import DashboardService


def get_dashboard_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DashboardService:
    return DashboardService(session)
