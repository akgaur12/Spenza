"""FastAPI dependency providers for the `import_export` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.import_export.export_service import ExportService
from src.modules.import_export.import_service import ImportService


def get_import_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ImportService:
    return ImportService(session)


def get_export_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportService:
    return ExportService(session)
