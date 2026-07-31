"""Data-access layer for the `categories` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `CategoryService` composes these to implement
behavior.
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.categories.models import Category


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, category_id: uuid.UUID) -> Category | None:
        return await self._session.get(Category, category_id)

    async def list_visible_to_user(
        self, user_id: uuid.UUID, *, search: str | None = None
    ) -> list[Category]:
        conditions = [
            Category.is_active.is_(True),
            or_(Category.user_id.is_(None), Category.user_id == user_id),
        ]
        if search:
            conditions.append(func.lower(Category.name).like(f"%{search.lower()}%"))
        result = await self._session.execute(
            select(Category).where(*conditions).order_by(Category.name)
        )
        return list(result.scalars().all())

    async def list_system(
        self, *, is_active: bool | None = None, search: str | None = None
    ) -> list[Category]:
        conditions = [Category.user_id.is_(None)]
        if is_active is not None:
            conditions.append(Category.is_active.is_(is_active))
        if search:
            conditions.append(func.lower(Category.name).like(f"%{search.lower()}%"))
        result = await self._session.execute(
            select(Category).where(*conditions).order_by(Category.name)
        )
        return list(result.scalars().all())

    async def find_by_name(
        self,
        user_id: uuid.UUID | None,
        name: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> Category | None:
        conditions = [
            Category.user_id.is_(None) if user_id is None else Category.user_id == user_id,
            func.lower(Category.name) == name.lower(),
        ]
        if exclude_id is not None:
            conditions.append(Category.id != exclude_id)
        result = await self._session.execute(select(Category).where(*conditions))
        return result.scalar_one_or_none()

    def create(self, *, user_id: uuid.UUID | None, name: str, icon: str | None) -> Category:
        category = Category(user_id=user_id, name=name, icon=icon)
        self._session.add(category)
        return category

    async def flush(self) -> None:
        await self._session.flush()
