"""Single import point for Alembic autogenerate: re-exports the shared
declarative `Base` and imports every module's ORM models so they register
themselves on `Base.metadata`.
"""

from src.core.database import Base
from src.modules.users.models import EmailOTP, RefreshSession, User

__all__ = ["Base", "EmailOTP", "RefreshSession", "User"]
