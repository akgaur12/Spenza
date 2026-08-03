"""Data-access layer for `ImportSession`.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `ImportService` composes these to implement
behavior.
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.import_export.models import ImportSession, ImportSessionStatus


class ImportSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        file_name: str,
        row_count: int,
        rows: list[dict[str, Any]],
        expires_at: datetime,
    ) -> ImportSession:
        import_session = ImportSession(
            user_id=user_id,
            file_name=file_name,
            row_count=row_count,
            rows=rows,
            expires_at=expires_at,
        )
        self._session.add(import_session)
        return import_session

    async def get_by_id_for_user(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ImportSession | None:
        result = await self._session.execute(
            select(ImportSession).where(
                ImportSession.id == session_id, ImportSession.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def mark_confirmed_if_pending(self, session_id: uuid.UUID) -> bool:
        """Atomically flip `pending` -> `confirmed`, returning whether this
        call was the one that made the change. A concurrent duplicate
        confirmation of the same session sees `False` and must not proceed
        to insert anything — this is the sole guard against double-import,
        so it must run as a single conditional `UPDATE`, never a
        read-then-write from Python.
        """
        result = await self._session.execute(
            update(ImportSession)
            .where(
                ImportSession.id == session_id,
                ImportSession.status == ImportSessionStatus.PENDING,
            )
            .values(status=ImportSessionStatus.CONFIRMED)
        )
        return bool(cast(CursorResult[Any], result).rowcount)

    async def flush(self) -> None:
        await self._session.flush()
