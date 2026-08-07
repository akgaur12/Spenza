"""FastAPI dependency providers for the `reports` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.reports.service import ReportService


def get_report_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReportService:
    return ReportService(session)
