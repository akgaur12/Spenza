"""ORM model for the `categories` module.

A single `Category` table serves both system/default categories
(`user_id IS NULL`, managed by admins) and user-created custom categories
(`user_id` set, managed by their owner). `user_id IS NULL` is the single
source of truth for "is this a system category" — no separate flag.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin


class Category(TimestampMixin, Base):
    """An expense category, either system-owned (`user_id is None`) or
    owned by a single user.
    """

    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_user_id_is_active", "user_id", "is_active"),
        # Functional index on lower(name) speeds up case-insensitive lookups
        # and search; the case-insensitive *uniqueness* constraints are
        # separate partial unique indexes created in the Alembic migration
        # (Postgres-only `WHERE` clauses aren't portable to the SQLite
        # metadata used by the test suite).
        Index("ix_categories_name_lower", text("lower(name)")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"Category(id={self.id}, name={self.name!r}, user_id={self.user_id})"
