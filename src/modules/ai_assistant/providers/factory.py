"""`LLMFactory`: the single place that maps an `LLMProvider` to a concrete
adapter and builds a LangChain `Runnable` from it.

This is the only import boundary between the agent/graph and any
provider-specific code — `agent/graph.py` calls `LLMFactory.create()` and
never imports `ChatOpenAI`/`ChatOllama`/`ChatBedrockConverse` or any
provider adapter class itself.
"""

from collections.abc import Sequence

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.exceptions import ProviderUnavailableError
from src.modules.ai_assistant.providers import config
from src.modules.ai_assistant.providers.aws_bedrock_provider import AWSBedrockProvider
from src.modules.ai_assistant.providers.base import BaseLLMProvider
from src.modules.ai_assistant.providers.capabilities import (
    ProviderCapabilities,
    ensure_required_capabilities,
    resolve_capabilities,
)
from src.modules.ai_assistant.providers.groq_provider import GroqProvider
from src.modules.ai_assistant.providers.huggingface_provider import HuggingFaceProvider
from src.modules.ai_assistant.providers.nvidia_provider import NvidiaProvider
from src.modules.ai_assistant.providers.ollama_provider import OllamaProvider
from src.modules.ai_assistant.providers.open_router_provider import OpenRouterProvider
from src.modules.ai_assistant.providers.openai_provider import OpenAIProvider

_ADAPTERS: dict[LLMProvider, type[BaseLLMProvider]] = {
    LLMProvider.OLLAMA: OllamaProvider,
    LLMProvider.AWS_BEDROCK: AWSBedrockProvider,
    LLMProvider.GROQ: GroqProvider,
    LLMProvider.NVIDIA: NvidiaProvider,
    LLMProvider.OPENAI: OpenAIProvider,
    LLMProvider.HUGGINGFACE: HuggingFaceProvider,
    LLMProvider.OPEN_ROUTER: OpenRouterProvider,
}


class LLMFactory:
    """Builds a provider-agnostic chat `Runnable` for a given
    provider/model, with `tools` already bound if supplied.
    """

    @staticmethod
    def create(
        provider: LLMProvider, model: str, *, tools: Sequence[BaseTool] | None = None
    ) -> tuple[Runnable[LanguageModelInput, AIMessage], ProviderCapabilities]:
        if not config.is_configured(provider):
            raise ProviderUnavailableError(
                f"The {provider.value} provider is not configured on this server."
            )

        capabilities = resolve_capabilities(provider, model)
        ensure_required_capabilities(capabilities, provider, model)

        adapter = _ADAPTERS[provider]()
        chat_model = adapter.create_model(model, tools=tools)
        return chat_model, capabilities
