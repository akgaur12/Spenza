"""FastAPI dependency providers for the `notifications` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.notifications.preferences.service import NotificationPreferenceService
from src.modules.notifications.service import NotificationService
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationService:
    return NotificationService(session)


def get_notification_preference_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationPreferenceService:
    return NotificationPreferenceService(session)


def get_email_delivery_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmailDeliveryService:
    return EmailDeliveryService(session)
