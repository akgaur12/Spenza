"""Reusable field-level validation helpers shared across request schemas."""

import re

from src.core.app_config import settings

_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,29}$")
_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"\d")
_SPECIAL_RE = re.compile(r"[^\w\s]")


def validate_username(value: str) -> str:
    """3-30 chars, must start with a letter, alphanumeric/underscore only."""
    value = value.strip()
    if not _USERNAME_RE.match(value):
        raise ValueError(
            "Username must be 3-30 characters, start with a letter, and contain "
            "only letters, numbers, and underscores"
        )
    return value


def validate_password_strength(value: str) -> str:
    """Enforce minimum length plus upper/lower/digit/special-character complexity."""
    errors: list[str] = []
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"be at least {settings.PASSWORD_MIN_LENGTH} characters long")
    if not _UPPERCASE_RE.search(value):
        errors.append("contain an uppercase letter")
    if not _LOWERCASE_RE.search(value):
        errors.append("contain a lowercase letter")
    if not _DIGIT_RE.search(value):
        errors.append("contain a digit")
    if not _SPECIAL_RE.search(value):
        errors.append("contain a special character")

    if errors:
        raise ValueError("Password must " + ", ".join(errors))
    return value
