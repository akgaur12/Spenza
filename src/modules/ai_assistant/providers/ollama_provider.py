"""Ollama provider adapter — a local/self-hosted model server, so this is
base-URL only, no API key.
"""

from collections.abc import Sequence

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from src.core.app_config import settings
from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.providers.base import BaseLLMProvider
from src.modules.ai_assistant.providers.capabilities import (
    ProviderCapabilities,
    resolve_capabilities,
)


class OllamaProvider(BaseLLMProvider):
    name = "ollama"

    def is_configured(self) -> bool:
        return bool(settings.OLLAMA_BASE_URL)

    def create_model(
        self, model: str, *, tools: Sequence[BaseTool] | None = None
    ) -> Runnable[LanguageModelInput, AIMessage]:
        chat_model = ChatOllama(
            model=model,
            base_url=settings.OLLAMA_BASE_URL,
            client_kwargs={"timeout": settings.AI_LLM_TIMEOUT_SECONDS},
        )
        return chat_model.bind_tools(tools) if tools else chat_model

    def capabilities(self, model: str) -> ProviderCapabilities:
        return resolve_capabilities(LLMProvider.OLLAMA, model)
