"""ORM model for the `expenses` module.

Each row is a single spending record private to its owning user. Every
expense belongs to exactly one category, which may be a system category
(`Category.user_id is None`) or a custom category owned by the same user.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base, TimestampMixin, UTCDateTime
from src.modules.categories.models import Category


class Expense(TimestampMixin, Base):
    """A single expense recorded by a user against a category."""

    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        # Covers the dominant query: a user's expenses ordered by spend date.
        Index("ix_expenses_user_id_spent_at", "user_id", "spent_at"),
        Index("ix_expenses_user_id_category_id", "user_id", "category_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    spent_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    # Forward-only relationship (no back_populates) — `Category` has no
    # `expenses` collection, mirroring the FK-only style already used
    # between `Category` and `User`. Not eager by default; call sites that
    # need category data load it explicitly (see `ExpenseRepository`).
    category: Mapped[Category] = relationship()

    def __repr__(self) -> str:
        return f"Expense(id={self.id}, user_id={self.user_id}, amount={self.amount})"
