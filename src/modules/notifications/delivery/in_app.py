"""In-app delivery.

The database row *is* the in-app notification — by the time
`NotificationService` calls this channel, the row is already committed and
visible to `GET /api/v1/notifications`. This class exists so the
invocation is uniform across channels (see `base.py`) and so a future
in-app-specific push mechanism (e.g. a WebSocket broadcast so an open tab
updates live, rather than waiting for the next poll) has an obvious home
that doesn't touch `NotificationService` itself.
"""

from src.core.logger import get_logger
from src.modules.notifications.delivery.base import BaseNotificationChannel
from src.modules.notifications.models import Notification

logger = get_logger(__name__)


class InAppChannel(BaseNotificationChannel):
    async def send(self, notification: Notification) -> None:
        logger.info(
            "notification.channel.invoked",
            channel="in_app",
            notification_id=str(notification.id),
            user_id=str(notification.user_id),
        )
