"""Delivery channel abstraction.

`NotificationService` never branches on "which channel" itself — it holds
a `dict[DeliveryChannel, BaseNotificationChannel]` and calls `.send()`
uniformly on whichever channels a user's preferences enable. Adding a new
channel (WebSocket push, Slack, SMS, ...) in a future phase means writing
one new class here and registering it — `NotificationService.send()` does
not change.
"""

from abc import ABC, abstractmethod

from src.modules.notifications.models import Notification


class BaseNotificationChannel(ABC):
    """One delivery mechanism for an already-persisted `Notification`.

    `send()` receives the notification *after* `NotificationService` has
    already created and flushed its row — a channel's job is purely
    "deliver this", never "decide whether to create it" (that's the
    preference check, done once by the service before any channel runs).
    """

    @abstractmethod
    async def send(self, notification: Notification) -> None: ...
