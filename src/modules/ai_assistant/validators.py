"""Reusable field-level validation helpers for `ai_assistant` request schemas."""

MAX_TITLE_LENGTH = 255
MAX_MESSAGE_LENGTH = 4000


def validate_title(value: str) -> str:
    """Trim surrounding whitespace and reject an empty/whitespace-only title."""
    value = value.strip()
    if not value:
        raise ValueError("Title cannot be empty")
    return value


def validate_message(value: str) -> str:
    """Trim surrounding whitespace and reject an empty/whitespace-only message."""
    value = value.strip()
    if not value:
        raise ValueError("Message cannot be empty")
    return value
