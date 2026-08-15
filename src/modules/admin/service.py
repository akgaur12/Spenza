"""Business logic for the cross-cutting `admin` module.

`AdminStatsService` aggregates counts across every domain module for the
system-overview dashboard. Read-only and admin-only — it runs plain
aggregate queries directly against the ORM models rather than going through
each domain's own repository, since none of those repositories expose (or
should expose) cross-user aggregate counts for their own use cases.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.admin.schemas import (
    AdminStatsOverview,
    CategoryStats,
    ExpenseStats,
    NotificationStats,
    RecurringExpenseStats,
    UserStats,
)
from src.modules.categories.models import Category
from src.modules.expenses.models import Expense
from src.modules.notifications.enums import DeliveryLogStatus
from src.modules.notifications.models import Notification, NotificationDeliveryLog
from src.modules.recurring_expenses.enums import RecurringExpenseStatus
from src.modules.recurring_expenses.models import RecurringExpense
from src.modules.users.models import User, UserRole


class AdminStatsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_overview(self) -> AdminStatsOverview:
        now = datetime.now(UTC)
        last_7_days = now - timedelta(days=7)
        last_30_days = now - timedelta(days=30)

        users = await self._user_stats(last_7_days, last_30_days)
        expenses = await self._expense_stats(last_30_days)
        recurring_expenses = await self._recurring_expense_stats()
        categories = await self._category_stats()
        notifications = await self._notification_stats(last_7_days)

        return AdminStatsOverview(
            users=users,
            expenses=expenses,
            recurring_expenses=recurring_expenses,
            categories=categories,
            notifications=notifications,
        )

    async def _user_stats(self, last_7_days: datetime, last_30_days: datetime) -> UserStats:
        total = await self._session.scalar(select(func.count()).select_from(User))
        active = await self._session.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
        verified = await self._session.scalar(
            select(func.count()).select_from(User).where(User.is_verified.is_(True))
        )
        admins = await self._session.scalar(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        locked = await self._session.scalar(
            select(func.count()).select_from(User).where(User.locked_until > datetime.now(UTC))
        )
        signups_7d = await self._session.scalar(
            select(func.count()).select_from(User).where(User.created_at >= last_7_days)
        )
        signups_30d = await self._session.scalar(
            select(func.count()).select_from(User).where(User.created_at >= last_30_days)
        )
        total = total or 0
        active = active or 0
        return UserStats(
            total=total,
            active=active,
            inactive=total - active,
            verified=verified or 0,
            admins=admins or 0,
            locked=locked or 0,
            signups_last_7_days=signups_7d or 0,
            signups_last_30_days=signups_30d or 0,
        )

    async def _expense_stats(self, last_30_days: datetime) -> ExpenseStats:
        total_count = await self._session.scalar(select(func.count()).select_from(Expense))
        total_amount = await self._session.scalar(select(func.sum(Expense.amount)))
        created_last_30_days = await self._session.scalar(
            select(func.count()).select_from(Expense).where(Expense.created_at >= last_30_days)
        )
        return ExpenseStats(
            total_count=total_count or 0,
            total_amount=total_amount or Decimal("0"),
            created_last_30_days=created_last_30_days or 0,
        )

    async def _recurring_expense_stats(self) -> RecurringExpenseStats:
        total = await self._session.scalar(select(func.count()).select_from(RecurringExpense))
        active = await self._session.scalar(
            select(func.count())
            .select_from(RecurringExpense)
            .where(RecurringExpense.status == RecurringExpenseStatus.ACTIVE)
        )
        return RecurringExpenseStats(total=total or 0, active=active or 0)

    async def _category_stats(self) -> CategoryStats:
        system_count = await self._session.scalar(
            select(func.count()).select_from(Category).where(Category.user_id.is_(None))
        )
        custom_count = await self._session.scalar(
            select(func.count()).select_from(Category).where(Category.user_id.is_not(None))
        )
        return CategoryStats(system_count=system_count or 0, custom_count=custom_count or 0)

    async def _notification_stats(self, last_7_days: datetime) -> NotificationStats:
        total_sent = await self._session.scalar(select(func.count()).select_from(Notification))
        failures_7d = await self._session.scalar(
            select(func.count())
            .select_from(NotificationDeliveryLog)
            .where(
                NotificationDeliveryLog.status == DeliveryLogStatus.FAILED,
                NotificationDeliveryLog.created_at >= last_7_days,
            )
        )
        return NotificationStats(
            total_sent=total_sent or 0, delivery_failures_last_7_days=failures_7d or 0
        )
