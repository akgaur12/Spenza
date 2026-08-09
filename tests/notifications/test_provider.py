"""Unit tests for the email provider abstraction.

`aiosmtplib.send` is mocked throughout — this module must never touch a
real network socket.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.app_config import settings
from src.modules.notifications.delivery.provider import EmailAttachment
from src.modules.notifications.delivery.smtp_provider import (
    ConsoleEmailProvider,
    SMTPProvider,
    get_email_provider,
)


async def test_console_provider_never_touches_the_network() -> None:
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await ConsoleEmailProvider().send_email(
            to="a@example.com", subject="Hi", html_body="<p>x</p>"
        )
        mock_send.assert_not_called()


async def test_smtp_provider_sends_via_aiosmtplib() -> None:
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await SMTPProvider().send_email(
            to="user@example.com", subject="Test subject", html_body="<p>Hello</p>"
        )
        mock_send.assert_awaited_once()
        message = mock_send.call_args.args[0]
        assert message["To"] == "user@example.com"
        assert message["Subject"] == "Test subject"
        assert message.get_content_type() == "multipart/mixed" or message.is_multipart()


async def test_smtp_provider_attaches_files() -> None:
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        attachment = EmailAttachment(
            filename="report.pdf", content=b"%PDF-1.4 fake", mime_type="application/pdf"
        )
        await SMTPProvider().send_email(
            to="user@example.com",
            subject="Your report",
            html_body="<p>Attached</p>",
            attachments=[attachment],
        )
        message = mock_send.call_args.args[0]
        filenames = [part.get_filename() for part in message.iter_attachments()]
        assert "report.pdf" in filenames


async def test_smtp_provider_propagates_send_failures() -> None:
    with (
        patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=OSError("smtp down")),
        pytest.raises(OSError, match="smtp down"),
    ):
        await SMTPProvider().send_email(to="user@example.com", subject="Hi", html_body="<p>x</p>")


def test_get_email_provider_defaults_to_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "console")
    assert isinstance(get_email_provider(), ConsoleEmailProvider)


def test_get_email_provider_returns_smtp_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    assert isinstance(get_email_provider(), SMTPProvider)
