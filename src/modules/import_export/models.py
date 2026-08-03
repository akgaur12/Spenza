"""ORM model for the `import_export` module.

`ImportSession` is a short-lived, server-side record of the rows a
`POST /api/v1/import/expenses/preview` call already validated for one user.
The signed `import_token` returned by that endpoint only ever carries this
row's id (see `import_service.py`) — never the row data itself — so
`POST /api/v1/import/expenses/confirm` always re-reads the previously
validated payload from here rather than trusting anything the client sends
back. This is not part of the core expense data model: it is deleted
implicitly by `expires_at` going stale (rows are simply never read again;
see `import_service.py` for the confirm-time expiry check) and carries no
foreign key from `expenses`.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UTCDateTime


class ImportSessionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class ImportSession(TimestampMixin, Base):
    """A batch of previously validated import rows awaiting confirmation."""

    __tablename__ = "import_sessions"
    __table_args__ = (Index("ix_import_sessions_user_id_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Each element is `{"category_id": str, "description": str, "amount":
    # str, "spent_at": str}` — already-validated, ready to become an
    # `ExpenseCreate` at confirm time. Never raw/unvalidated file content.
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[ImportSessionStatus] = mapped_column(
        Enum(ImportSessionStatus, native_enum=False, length=20),
        default=ImportSessionStatus.PENDING,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    def __repr__(self) -> str:
        return f"ImportSession(id={self.id}, user_id={self.user_id}, status={self.status})"
