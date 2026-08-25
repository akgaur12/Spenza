"""Fixtures shared by every `ai_assistant` test: seeded system categories
(the real seed migration never runs against the test suite's SQLite DB —
see `tests/recurring_expenses/conftest.py` for the same pattern), a
disabled-by-default title-generation flag (so unrelated tests don't race a
background task), and a one-call helper to make `LLMFactory.create` return
a scripted `FakeChatModel` instead of ever touching a real provider.
"""

from collections.abc import Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.modules.ai_assistant.providers.capabilities import ProviderCapabilities
from src.modules.ai_assistant.providers.factory import LLMFactory
from src.modules.categories.models import Category
from src.modules.categories.seed_data import DEFAULT_SYSTEM_CATEGORIES
from tests.ai_assistant.fakes import FakeChatModel

InstallFakeModel = Callable[[FakeChatModel], None]


@pytest_asyncio.fixture(autouse=True)
async def _seed_system_categories(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        for name, icon in DEFAULT_SYSTEM_CATEGORIES:
            session.add(Category(user_id=None, name=name, icon=icon))
        await session.commit()


@pytest.fixture(autouse=True)
def _disable_title_generation_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AI_TITLE_GENERATION_ENABLED", False)


@pytest.fixture
def install_fake_model(monkeypatch: pytest.MonkeyPatch) -> InstallFakeModel:
    """Returns `install(fake_model)`. After calling it, every
    `LLMFactory.create(...)` in the test returns `fake_model` (with
    streaming/tool-calling capabilities), regardless of the chat's actual
    `provider`/`model` — no real provider class is ever touched.
    """

    def _install(fake_model: FakeChatModel) -> None:
        def fake_create(
            provider: object, model: object, *, tools: object = None
        ) -> tuple[FakeChatModel, ProviderCapabilities]:
            return fake_model, ProviderCapabilities(
                streaming=True, tool_calling=True, structured_output=True
            )

        monkeypatch.setattr(LLMFactory, "create", fake_create)

    return _install
