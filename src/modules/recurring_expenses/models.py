"""ORM model for the `recurring_expenses` module.

A `RecurringExpense` row is an expense *template* — never an expense
itself. The scheduler (see `scheduler.py`) turns it into a real `Expense`
row via `ExpenseService.create_for_user`, exactly like a manually created
expense, and never inserts into the `expenses` table directly. Generated
expenses are not linked back here (no stored expense IDs): once created,
they're indistinguishable from manual ones and remain independent of the
recurring definition that produced them.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base, TimestampMixin
from src.modules.categories.models import Category
from src.modules.recurring_expenses.enums import Frequency, GenerationMode, RecurringExpenseStatus


class RecurringExpense(TimestampMixin, Base):
    """A user-defined template for automatically generating expenses on a
    schedule (see the module docstring for the generation flow).
    """

    __tablename__ = "recurring_expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_recurring_expenses_amount_positive"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_recurring_expenses_end_date_after_start",
        ),
        # Covers the scheduler's dominant query: active rows due today.
        Index("ix_recurring_expenses_status_next_run_date", "status", "next_run_date"),
        Index("ix_recurring_expenses_user_id_status", "user_id", "status"),
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

    frequency: Mapped[Frequency] = mapped_column(
        Enum(Frequency, native_enum=False, length=20), nullable=False
    )
    generation_mode: Mapped[GenerationMode] = mapped_column(
        Enum(GenerationMode, native_enum=False, length=20), nullable=False
    )
    status: Mapped[RecurringExpenseStatus] = mapped_column(
        Enum(RecurringExpenseStatus, native_enum=False, length=20),
        default=RecurringExpenseStatus.ACTIVE,
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_run_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Forward-only relationship (no back_populates), same style as
    # `Expense.category` — not eager by default, loaded explicitly where
    # needed (see `RecurringExpenseRepository`).
    category: Mapped[Category] = relationship()

    def __repr__(self) -> str:
        return (
            f"RecurringExpense(id={self.id}, user_id={self.user_id}, "
            f"frequency={self.frequency}, status={self.status})"
        )
