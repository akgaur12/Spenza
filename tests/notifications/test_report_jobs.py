"""Tests for the scheduled monthly/yearly report generation + delivery job.

Uses the real `ConsoleEmailProvider` (the test suite's `EMAIL_BACKEND`
default) rather than a fake — it never raises, so "was the report
delivered" is asserted via the `notification_delivery_logs` row and the
created `REPORT_READY` notification, not via a mocked provider.
"""

from datetime import date

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.categories.models import Category
from src.modules.categories.seed_data import DEFAULT_SYSTEM_CATEGORIES
from src.modules.notifications.enums import DeliveryLogStatus, NotificationType
from src.modules.notifications.jobs.report_jobs import (
    build_report_email,
    previous_month,
    process_monthly_reports,
    process_yearly_reports,
)
from src.modules.notifications.models import Notification, NotificationDeliveryLog
from src.modules.reports.schemas import ReportType
from src.modules.reports.service import ReportService
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, category_id_by_name, create_expense, login_user_a
from tests.notifications.helpers import update_notification_preference


@pytest_asyncio.fixture(autouse=True)
async def _seed_system_categories(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_factory() as session:
        for name, icon in DEFAULT_SYSTEM_CATEGORIES:
            session.add(Category(user_id=None, name=name, icon=icon))
        await session.commit()


def test_previous_month_handles_year_rollover() -> None:
    assert previous_month(date(2026, 1, 15)) == (2025, 12)
    assert previous_month(date(2026, 3, 1)) == (2026, 2)


async def test_process_monthly_reports_is_a_no_op_off_the_delivery_day(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        summary = await process_monthly_reports(session, today=date(2026, 3, 15))
        assert summary.eligible_users == 0
        assert summary.sent == 0


async def test_process_monthly_reports_skips_users_without_email_preference(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    async with db_session_factory() as session:
        summary = await process_monthly_reports(session, today=date(2026, 3, 1))
        assert summary.eligible_users == 0
        assert summary.sent == 0


async def test_process_monthly_reports_delivers_for_opted_in_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Groceries",
        amount="45.00",
        spent_at="2026-02-10T12:00:00+05:30",
    )
    await update_notification_preference(client, "report_ready", {"email_enabled": True})

    async with db_session_factory() as session:
        summary = await process_monthly_reports(session, today=date(2026, 3, 1))

        assert summary.eligible_users == 1
        assert summary.sent == 1
        assert summary.failed == 0

        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None

        notifications = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id == user.id,
                        Notification.type == NotificationType.REPORT_READY,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifications) == 1
        assert "February 2026" in notifications[0].title

        logs = (
            (
                await session.execute(
                    select(NotificationDeliveryLog).where(
                        NotificationDeliveryLog.notification_id == notifications[0].id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(log.status is DeliveryLogStatus.SUCCESS for log in logs)


async def test_process_yearly_reports_is_a_no_op_off_the_delivery_day(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        summary = await process_yearly_reports(session, today=date(2026, 6, 1))
        assert summary.eligible_users == 0
        assert summary.sent == 0


async def test_process_yearly_reports_delivers_for_opted_in_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Groceries",
        amount="45.00",
        spent_at="2025-06-10T12:00:00+05:30",
    )
    await update_notification_preference(client, "report_ready", {"email_enabled": True})

    async with db_session_factory() as session:
        summary = await process_yearly_reports(session, today=date(2026, 1, 1))
        assert summary.eligible_users == 1
        assert summary.sent == 1


async def test_build_report_email_uses_monthly_template_and_subject(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Groceries",
        amount="45.00",
        spent_at="2026-02-10T12:00:00+05:30",
    )
    async with db_session_factory() as session:
        from src.modules.reports.schemas import ReportRequest

        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        _, data, _ = await ReportService(session).generate_with_data(
            user, ReportRequest(type=ReportType.MONTHLY, year=2026, month=2)
        )
        subject, template_name, context = build_report_email(ReportType.MONTHLY, data)
        assert subject == "Your February 2026 Expense Report"
        assert template_name == "monthly_report.html"
        assert context["expense_count"] == 1


async def test_build_report_email_uses_yearly_template_and_subject(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    async with db_session_factory() as session:
        from src.modules.reports.schemas import ReportRequest

        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        _, data, _ = await ReportService(session).generate_with_data(
            user, ReportRequest(type=ReportType.YEARLY, year=2025)
        )
        subject, template_name, _ = build_report_email(ReportType.YEARLY, data)
        assert subject == "Your 2025 Annual Expense Report"
        assert template_name == "yearly_report.html"
