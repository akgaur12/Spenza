"""Reusable field-level validation helpers for notification-preference
request schemas.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_timezone(value: str) -> str:
    """Reject anything that isn't a real IANA timezone name — stored now,
    read by Phase 11B's scheduled digest delivery, so a typo caught at
    write time is far cheaper than one discovered when a digest silently
    never fires.
    """
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {value!r}") from exc
    return value
