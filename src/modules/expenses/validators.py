"""Reusable field-level validation helpers for expense request schemas."""


def validate_description(value: str) -> str:
    """Trim surrounding whitespace and reject an empty/whitespace-only description."""
    value = value.strip()
    if not value:
        raise ValueError("Description cannot be empty")
    return value
