"""The provider interface every LLM adapter implements.

`LLMFactory` (see `factory.py`) is the only caller of `create_model()` — the
agent/graph never imports a concrete provider or a LangChain chat-model
class directly, only the `Runnable` this returns.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.modules.ai_assistant.providers.capabilities import ProviderCapabilities


class BaseLLMProvider(ABC):
    """One LLM backend. `name` identifies the provider in logs/metadata."""

    name: ClassVar[str]

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider's required credentials are present."""

    @abstractmethod
    def create_model(
        self, model: str, *, tools: Sequence[BaseTool] | None = None
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Build a LangChain chat model for `model`, with `tools` bound if
        given. Never raises for a missing model name — an invalid model is
        surfaced by the provider's API at call time, not construction time.
        """

    @abstractmethod
    def capabilities(self, model: str) -> ProviderCapabilities:
        """Best-effort capability metadata for `model` on this provider."""
