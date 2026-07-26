"""Shared `slowapi` rate limiter instance.

Endpoints opt in with `@limiter.limit(settings.RATE_LIMIT_AUTH)` etc.
Registered on the app (state + middleware + exception handler) in `src/app.py`.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.app_config import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)
