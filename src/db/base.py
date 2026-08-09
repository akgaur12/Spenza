"""Single import point for Alembic autogenerate: re-exports the shared
declarative `Base` and imports every module's ORM models so they register
themselves on `Base.metadata`.
"""

from src.core.database import Base
from src.modules.categories.models import Category
from src.modules.expenses.models import Expense
from src.modules.import_export.models import ImportSession
from src.modules.notifications.models import Notification, NotificationPreference
from src.modules.recurring_expenses.models import RecurringExpense
from src.modules.users.models import EmailOTP, RefreshSession, User

__all__ = [
    "Base",
    "Category",
    "EmailOTP",
    "Expense",
    "ImportSession",
    "Notification",
    "NotificationPreference",
    "RecurringExpense",
    "RefreshSession",
    "User",
]
