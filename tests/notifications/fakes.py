"""Test doubles for the Phase 11B email delivery pipeline."""

from src.modules.notifications.delivery.provider import BaseEmailProvider, EmailAttachment


class RecordingEmailProvider(BaseEmailProvider):
    """Records every `send_email` call instead of delivering it.

    `fail_times` lets a test simulate N transient provider failures before
    the (N+1)th call succeeds — used by `EmailDeliveryService`'s retry
    tests; `always_fail` simulates permanent provider unavailability.
    """

    name = "fake"

    def __init__(self, *, fail_times: int = 0, always_fail: bool = False) -> None:
        self.sent: list[dict[str, object]] = []
        self.call_count = 0
        self._fail_times = fail_times
        self._always_fail = always_fail

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        self.call_count += 1
        if self._always_fail or self.call_count <= self._fail_times:
            raise RuntimeError("simulated provider failure")
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "html_body": html_body,
                "attachments": attachments or [],
            }
        )
