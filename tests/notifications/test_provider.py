"""Unit tests for the email provider abstraction.

`aiosmtplib.send` / `httpx.AsyncClient.post` are mocked throughout — this
module must never touch a real network socket.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.core.app_config import settings
from src.modules.notifications.delivery.mailjet_provider import MailjetProvider
from src.modules.notifications.delivery.provider import EmailAttachment
from src.modules.notifications.delivery.resend_provider import ResendProvider, _html_to_text
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


def test_get_email_provider_returns_resend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "resend")
    assert isinstance(get_email_provider(), ResendProvider)


async def test_resend_provider_posts_to_resend_api() -> None:
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await ResendProvider().send_email(
            to="user@example.com", subject="Test subject", html_body="<p>Hello</p>"
        )
        mock_post.assert_awaited_once()
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        assert url == "https://api.resend.com/emails"
        assert kwargs["json"]["to"] == ["user@example.com"]
        assert kwargs["json"]["subject"] == "Test subject"
        assert kwargs["json"]["text"] == "Hello"
        assert "attachments" not in kwargs["json"]


def test_html_to_text_strips_tags_and_collapses_blank_lines() -> None:
    html = "<p>Hi Akash,</p>\n\n\n<p>Your code is <strong>123456</strong>.</p>"
    assert _html_to_text(html) == "Hi Akash,\n\nYour code is 123456."


async def test_resend_provider_attaches_files_as_base64() -> None:
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()
    attachment = EmailAttachment(
        filename="report.pdf", content=b"%PDF-1.4 fake", mime_type="application/pdf"
    )
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await ResendProvider().send_email(
            to="user@example.com",
            subject="Your report",
            html_body="<p>Attached</p>",
            attachments=[attachment],
        )
        payload = mock_post.call_args.kwargs["json"]
        expected_content = base64.b64encode(b"%PDF-1.4 fake").decode("ascii")
        assert payload["attachments"] == [{"filename": "report.pdf", "content": expected_content}]


async def test_resend_provider_propagates_send_failures() -> None:
    mock_response = MagicMock(status_code=422)
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=mock_response
        )
    )
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await ResendProvider().send_email(to="user@example.com", subject="Hi", html_body="<p>x</p>")


def test_get_email_provider_returns_mailjet_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "mailjet")
    assert isinstance(get_email_provider(), MailjetProvider)


async def test_mailjet_provider_posts_to_mailjet_api() -> None:
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await MailjetProvider().send_email(
            to="user@example.com", subject="Test subject", html_body="<p>Hello</p>"
        )
        mock_post.assert_awaited_once()
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        assert url == "https://api.mailjet.com/v3.1/send"
        message = kwargs["json"]["Messages"][0]
        assert message["To"] == [{"Email": "user@example.com"}]
        assert message["Subject"] == "Test subject"
        assert message["TextPart"] == "Hello"
        assert "Attachments" not in message


async def test_mailjet_provider_attaches_files_as_base64() -> None:
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()
    attachment = EmailAttachment(
        filename="report.pdf", content=b"%PDF-1.4 fake", mime_type="application/pdf"
    )
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await MailjetProvider().send_email(
            to="user@example.com",
            subject="Your report",
            html_body="<p>Attached</p>",
            attachments=[attachment],
        )
        message = mock_post.call_args.kwargs["json"]["Messages"][0]
        expected_content = base64.b64encode(b"%PDF-1.4 fake").decode("ascii")
        assert message["Attachments"] == [
            {
                "ContentType": "application/pdf",
                "Filename": "report.pdf",
                "Base64Content": expected_content,
            }
        ]


async def test_mailjet_provider_propagates_send_failures() -> None:
    mock_response = MagicMock(status_code=401)
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "unauthorized", request=MagicMock(), response=mock_response
        )
    )
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await MailjetProvider().send_email(
            to="user@example.com", subject="Hi", html_body="<p>x</p>"
        )
