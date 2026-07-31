"""FastAPI dependency providers for the `categories` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.categories.service import CategoryService


def get_category_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CategoryService:
    return CategoryService(session)
