"""Unit tests for the OTP/welcome-email backend abstraction.

`aiosmtplib.send` / `httpx.AsyncClient.post` are mocked throughout — this
module must never touch a real network socket.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.core.app_config import settings
from src.shared.email.backend import (
    ConsoleEmailBackend,
    MailjetEmailBackend,
    ResendEmailBackend,
    SMTPEmailBackend,
    _html_to_text,
    get_email_backend,
)


def test_html_to_text_strips_tags_and_collapses_blank_lines() -> None:
    html = "<p>Hi Akash,</p>\n\n\n<p>Your code is <strong>123456</strong>.</p>"
    assert _html_to_text(html) == "Hi Akash,\n\nYour code is 123456."


async def test_console_backend_never_touches_the_network() -> None:
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await ConsoleEmailBackend().send(to="a@example.com", subject="Hi", html_body="<p>x</p>")
        mock_send.assert_not_called()


async def test_smtp_backend_sends_via_aiosmtplib() -> None:
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await SMTPEmailBackend().send(
            to="user@example.com", subject="Test subject", html_body="<p>Hello</p>"
        )
        mock_send.assert_awaited_once()
        message = mock_send.call_args.args[0]
        assert message["To"] == "user@example.com"
        assert message["Subject"] == "Test subject"


async def test_resend_backend_posts_to_resend_api() -> None:
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await ResendEmailBackend().send(
            to="user@example.com", subject="Test subject", html_body="<p>Hello</p>"
        )
        mock_post.assert_awaited_once()
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        assert url == "https://api.resend.com/emails"
        assert kwargs["json"]["to"] == ["user@example.com"]
        assert kwargs["json"]["subject"] == "Test subject"
        assert kwargs["json"]["text"] == "Hello"


async def test_resend_backend_propagates_send_failures() -> None:
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
        await ResendEmailBackend().send(to="user@example.com", subject="Hi", html_body="<p>x</p>")


async def test_mailjet_backend_posts_to_mailjet_api() -> None:
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await MailjetEmailBackend().send(
            to="user@example.com", subject="Test subject", html_body="<p>Hello</p>"
        )
        mock_post.assert_awaited_once()
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        assert url == "https://api.mailjet.com/v3.1/send"
        message = kwargs["json"]["Messages"][0]
        assert message["To"] == [{"Email": "user@example.com"}]
        assert message["Subject"] == "Test subject"
        assert message["HTMLPart"] == "<p>Hello</p>"
        assert message["TextPart"] == "Hello"


async def test_mailjet_backend_propagates_send_failures() -> None:
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
        await MailjetEmailBackend().send(to="user@example.com", subject="Hi", html_body="<p>x</p>")


def test_get_email_backend_defaults_to_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "console")
    assert isinstance(get_email_backend(), ConsoleEmailBackend)


def test_get_email_backend_returns_smtp_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    assert isinstance(get_email_backend(), SMTPEmailBackend)


def test_get_email_backend_returns_resend_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "resend")
    assert isinstance(get_email_backend(), ResendEmailBackend)


def test_get_email_backend_returns_mailjet_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "mailjet")
    assert isinstance(get_email_backend(), MailjetEmailBackend)
