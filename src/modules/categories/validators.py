"""Reusable field-level validation helpers for category request schemas."""


def validate_category_name(value: str) -> str:
    """Trim surrounding whitespace and reject an empty/whitespace-only name."""
    value = value.strip()
    if not value:
        raise ValueError("Category name cannot be empty")
    return value
