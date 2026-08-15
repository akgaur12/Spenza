"""FastAPI dependency providers for the cross-cutting `admin` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.admin.service import AdminStatsService


def get_admin_stats_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminStatsService:
    return AdminStatsService(session)
