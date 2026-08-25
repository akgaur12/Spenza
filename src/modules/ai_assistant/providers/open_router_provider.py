"""OpenRouter provider adapter — OpenRouter exposes an OpenAI-compatible
chat-completions API in front of many underlying models, so it reuses
`ChatOpenAI` with a different `base_url`/`api_key`. Tool-calling support
depends on the specific model routed to — see `providers.capabilities`'s
denylist.
"""

from collections.abc import Sequence

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from src.core.app_config import settings
from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.providers.base import BaseLLMProvider
from src.modules.ai_assistant.providers.capabilities import (
    ProviderCapabilities,
    resolve_capabilities,
)

OPEN_ROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseLLMProvider):
    name = "open_router"

    def is_configured(self) -> bool:
        return bool(settings.OPEN_ROUTER_API_KEY)

    def create_model(
        self, model: str, *, tools: Sequence[BaseTool] | None = None
    ) -> Runnable[LanguageModelInput, AIMessage]:
        chat_model = ChatOpenAI(
            model=model,
            api_key=settings.OPEN_ROUTER_API_KEY,
            base_url=OPEN_ROUTER_BASE_URL,
            timeout=settings.AI_LLM_TIMEOUT_SECONDS,
        )
        return chat_model.bind_tools(tools) if tools else chat_model

    def capabilities(self, model: str) -> ProviderCapabilities:
        return resolve_capabilities(LLMProvider.OPEN_ROUTER, model)
