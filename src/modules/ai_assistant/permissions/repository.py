"""Data-access layer for `AIAssistantPermission`.

Database operations only — no business logic (in particular, no "what
should the default be" decision; see `service.py` for that).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ai_assistant.models import AIAssistantPermission


class AIAssistantPermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> AIAssistantPermission | None:
        result = await self._session.execute(
            select(AIAssistantPermission).where(AIAssistantPermission.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def create(self, *, user_id: uuid.UUID) -> AIAssistantPermission:
        """Creates a row seeded with the model's own column defaults
        (`enabled=False`, every limit `None`) — callers apply any
        requested overrides on top via `setattr` before flushing.
        """
        permission = AIAssistantPermission(user_id=user_id)
        self._session.add(permission)
        return permission

    async def flush(self) -> None:
        await self._session.flush()
