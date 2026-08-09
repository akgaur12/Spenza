"""Scheduled monthly/yearly report generation + delivery.

Runs daily (see `notifications.scheduler`) but only actually generates and
sends anything on the configured delivery day (and, for yearly, month) — see
`settings.MONTHLY_REPORT_DELIVERY_DAY` / `YEARLY_REPORT_DELIVERY_DAY` /
`YEARLY_REPORT_DELIVERY_MONTH`. There is no per-user "day of month"
preference yet (`NotificationPreference.delivery_time`/`timezone` capture a
time-of-day, not a day-of-month), so one global day applies to every user —
a deliberate scope decision for this phase, not an oversight.

`build_report_email()` is shared with `POST /reports/send-now`
(`reports.router`) so a scheduled report and an on-demand one always look
identical — same subject, same template, same summary figures.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.core.timezone import APP_TIMEZONE
from src.modules.notifications.delivery.provider import EmailAttachment
from src.modules.notifications.delivery.templates import render_template
from src.modules.notifications.enums import NotificationType
from src.modules.notifications.preferences.service import NotificationPreferenceService
from src.modules.notifications.service import NotificationService
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.reports.schemas import ReportData, ReportRequest, ReportType
from src.modules.reports.service import ReportService
from src.modules.users.models import User

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReportJobSummary:
    eligible_users: int
    sent: int
    failed: int


def build_report_email(
    report_type: ReportType, data: ReportData
) -> tuple[str, str, dict[str, object]]:
    """`(subject, template_name, template_context)` for `data` — the single
    place a report's email content is composed.
    """
    context: dict[str, object] = {
        "username": data.metadata.full_name or data.metadata.username,
        "period_label": data.metadata.period_label,
        "total_spending": data.summary.total_spending,
        "expense_count": data.summary.expense_count,
        "top_category": data.summary.top_category.name if data.summary.top_category else None,
        "largest_expense": (
            data.summary.largest_expense.amount if data.summary.largest_expense else None
        ),
    }
    if report_type is ReportType.YEARLY:
        return (
            f"Your {data.metadata.period_label} Annual Expense Report",
            "yearly_report.html",
            context,
        )
    return f"Your {data.metadata.period_label} Expense Report", "monthly_report.html", context


def previous_month(today: date) -> tuple[int, int]:
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    return last_day_prev_month.year, last_day_prev_month.month


async def _eligible_users(session: AsyncSession) -> list[User]:
    """Every active, verified user — the actual "wants this report" check
    (preference `enabled` + `email_enabled` for `REPORT_READY`) happens per
    user in the caller's loop, not here.
    """
    result = await session.execute(
        select(User).where(User.is_active.is_(True), User.is_verified.is_(True))
    )
    return list(result.scalars().all())


async def _generate_and_send(session: AsyncSession, user: User, request: ReportRequest) -> bool:
    """Creates the `REPORT_READY` notification *before* emailing the report
    — `EmailChannel` is a no-op for that type (see its docstring), so this
    ordering has no visible side effect, but it means the report's own
    delivery-log rows can reference the notification they belong to, which
    matters for `notification_delivery_logs`' debugging purpose.
    """
    pdf_bytes, data, filename = await ReportService(session).generate_with_data(user, request)
    subject, template_name, context = build_report_email(request.type, data)

    notification = await NotificationService(session).send(
        user_id=user.id,
        type=NotificationType.REPORT_READY,
        title=subject,
        message=f"Your {data.metadata.period_label} expense report has been sent to your email.",
        payload={"report_type": request.type.value, "period_label": data.metadata.period_label},
    )

    html_body = render_template(template_name, **context)
    return await EmailDeliveryService(session).send(
        to=user.email,
        subject=subject,
        html_body=html_body,
        attachments=[
            EmailAttachment(filename=filename, content=pdf_bytes, mime_type="application/pdf")
        ],
        notification_id=notification.id if notification else None,
    )


async def process_monthly_reports(
    session: AsyncSession, *, today: date | None = None
) -> ReportJobSummary:
    today = today or datetime.now(APP_TIMEZONE).date()
    if today.day != settings.MONTHLY_REPORT_DELIVERY_DAY:
        return ReportJobSummary(eligible_users=0, sent=0, failed=0)

    year, month = previous_month(today)
    preferences = NotificationPreferenceService(session)
    eligible = sent = failed = 0
    for user in await _eligible_users(session):
        preference = await preferences.get_for_user(user.id, NotificationType.REPORT_READY)
        if not (preference.enabled and preference.email_enabled):
            continue
        eligible += 1
        try:
            request = ReportRequest(type=ReportType.MONTHLY, year=year, month=month)
            delivered = await _generate_and_send(session, user, request)
        except Exception:
            logger.exception("report_job.monthly.user_failed", user_id=str(user.id))
            await session.rollback()
            failed += 1
            continue
        sent += 1 if delivered else 0
        failed += 0 if delivered else 1
        await session.commit()
    return ReportJobSummary(eligible_users=eligible, sent=sent, failed=failed)


async def process_yearly_reports(
    session: AsyncSession, *, today: date | None = None
) -> ReportJobSummary:
    today = today or datetime.now(APP_TIMEZONE).date()
    if (
        today.month != settings.YEARLY_REPORT_DELIVERY_MONTH
        or today.day != settings.YEARLY_REPORT_DELIVERY_DAY
    ):
        return ReportJobSummary(eligible_users=0, sent=0, failed=0)

    year = today.year - 1
    preferences = NotificationPreferenceService(session)
    eligible = sent = failed = 0
    for user in await _eligible_users(session):
        preference = await preferences.get_for_user(user.id, NotificationType.REPORT_READY)
        if not (preference.enabled and preference.email_enabled):
            continue
        eligible += 1
        try:
            request = ReportRequest(type=ReportType.YEARLY, year=year)
            delivered = await _generate_and_send(session, user, request)
        except Exception:
            logger.exception("report_job.yearly.user_failed", user_id=str(user.id))
            await session.rollback()
            failed += 1
            continue
        sent += 1 if delivered else 0
        failed += 0 if delivered else 1
        await session.commit()
    return ReportJobSummary(eligible_users=eligible, sent=sent, failed=failed)


async def run_monthly_report_job() -> None:
    async with AsyncSessionLocal() as session:
        try:
            summary = await process_monthly_reports(session)
            logger.info(
                "report_job.monthly.completed",
                eligible_users=summary.eligible_users,
                sent=summary.sent,
                failed=summary.failed,
            )
        except Exception:
            logger.exception("report_job.monthly.failed")


async def run_yearly_report_job() -> None:
    async with AsyncSessionLocal() as session:
        try:
            summary = await process_yearly_reports(session)
            logger.info(
                "report_job.yearly.completed",
                eligible_users=summary.eligible_users,
                sent=summary.sent,
                failed=summary.failed,
            )
        except Exception:
            logger.exception("report_job.yearly.failed")
