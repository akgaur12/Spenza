"""Business logic for the `categories` module.

Depends only on the repository + shared infra — never on FastAPI request /
response objects — so it stays fully unit-testable.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.modules.categories.exceptions import (
    CategoryAlreadyExistsError,
    CategoryNotFoundError,
    SystemCategoryReadOnlyError,
)
from src.modules.categories.models import Category
from src.modules.categories.repository import CategoryRepository
from src.modules.categories.schemas import AdminCategoryUpdate, CategoryCreate, CategoryUpdate
from src.modules.users.models import User

logger = get_logger(__name__)


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)

    # ── User-facing ──────────────────────────────────────────────────────

    async def list_for_user(self, user: User, *, search: str | None) -> list[Category]:
        return await self._categories.list_visible_to_user(user.id, search=search)

    async def get_for_user(self, category_id: uuid.UUID, user: User) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None or not category.is_active:
            raise CategoryNotFoundError()
        if category.user_id is not None and category.user_id != user.id:
            raise CategoryNotFoundError()
        return category

    async def create_for_user(self, user: User, data: CategoryCreate) -> Category:
        await self._ensure_name_available(user.id, data.name)
        category = self._categories.create(user_id=user.id, name=data.name, icon=data.icon)
        await self._flush_checked()
        logger.info("category.created", category_id=str(category.id), user_id=str(user.id))
        return category

    async def update_for_user(
        self, category_id: uuid.UUID, user: User, data: CategoryUpdate
    ) -> Category:
        category = await self._get_owned_by_user(category_id, user)
        updates = data.model_dump(exclude_unset=True)
        new_name = updates.get("name")
        if new_name is not None:
            await self._ensure_name_available(user.id, new_name, exclude_id=category.id)
        for field, value in updates.items():
            setattr(category, field, value)
        await self._flush_checked()
        logger.info("category.updated", category_id=str(category.id), user_id=str(user.id))
        return category

    async def delete_for_user(self, category_id: uuid.UUID, user: User) -> None:
        category = await self._get_owned_by_user(category_id, user)
        category.is_active = False
        await self._categories.flush()
        logger.info("category.deleted", category_id=str(category.id), user_id=str(user.id))

    async def _get_owned_by_user(self, category_id: uuid.UUID, user: User) -> Category:
        """Fetch a category the given user may modify (their own, active or
        not), distinguishing "doesn't exist / belongs to someone else"
        (404, never reveals another user's private category) from "exists
        but is a system category" (403, since that's public, expected
        information — system categories are visibly read-only).
        """
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise CategoryNotFoundError()
        if category.user_id is None:
            raise SystemCategoryReadOnlyError()
        if category.user_id != user.id:
            raise CategoryNotFoundError()
        return category

    # ── Admin-facing ─────────────────────────────────────────────────────

    async def list_system(self, *, is_active: bool | None, search: str | None) -> list[Category]:
        return await self._categories.list_system(is_active=is_active, search=search)

    async def create_system(self, data: CategoryCreate) -> Category:
        await self._ensure_name_available(None, data.name)
        category = self._categories.create(user_id=None, name=data.name, icon=data.icon)
        await self._flush_checked()
        logger.info("admin.category.created", category_id=str(category.id))
        return category

    async def update_system(self, category_id: uuid.UUID, data: AdminCategoryUpdate) -> Category:
        category = await self._get_system(category_id)
        updates = data.model_dump(exclude_unset=True)
        new_name = updates.get("name")
        if new_name is not None:
            await self._ensure_name_available(None, new_name, exclude_id=category.id)
        for field, value in updates.items():
            setattr(category, field, value)
        await self._flush_checked()
        logger.info("admin.category.updated", category_id=str(category.id))
        return category

    async def deactivate_system(self, category_id: uuid.UUID) -> None:
        category = await self._get_system(category_id)
        category.is_active = False
        await self._categories.flush()
        logger.info("admin.category.deactivated", category_id=str(category.id))

    async def _get_system(self, category_id: uuid.UUID) -> Category:
        """Only ever resolves a system category — a user-owned category ID
        is treated as not-found through this endpoint, never modified.
        """
        category = await self._categories.get_by_id(category_id)
        if category is None or category.user_id is not None:
            raise CategoryNotFoundError()
        return category

    # ── Shared ─────────────────────────────────────────────────────────────

    async def _ensure_name_available(
        self,
        user_id: uuid.UUID | None,
        name: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        existing = await self._categories.find_by_name(user_id, name, exclude_id=exclude_id)
        if existing is not None:
            raise CategoryAlreadyExistsError()

    async def _flush_checked(self) -> None:
        """Flush, translating a DB-level unique-index violation — a race
        between two concurrent requests that both passed the app-level
        pre-check — into the same clean `CategoryAlreadyExistsError`
        instead of a raw integrity error.
        """
        try:
            await self._categories.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise CategoryAlreadyExistsError() from exc
