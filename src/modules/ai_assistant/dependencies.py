"""FastAPI dependency providers for the `ai_assistant` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.ai_assistant.observability.service import AIAssistantObservabilityService
from src.modules.ai_assistant.permissions.service import AIAssistantPermissionService
from src.modules.ai_assistant.service import ChatService


def get_chat_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> ChatService:
    return ChatService(session)


def get_ai_assistant_permission_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIAssistantPermissionService:
    return AIAssistantPermissionService(session)


def get_ai_assistant_observability_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIAssistantObservabilityService:
    return AIAssistantObservabilityService(session)
