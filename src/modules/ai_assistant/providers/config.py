"""Resolves whether a given `LLMProvider` has the credentials it needs,
from `settings` only — never from a chat/message/run row. Mirrors
`notifications`'s `resend_configured`/`mailjet_configured` ad hoc
"is this backend's secret set" checks, generalized across 7 providers so
`LLMFactory` can fail fast with a clear `ProviderUnavailableError` instead
of a raw SDK validation error.
"""

from collections.abc import Callable

from src.core.app_config import settings
from src.modules.ai_assistant.enums import LLMProvider

_CHECKS: dict[LLMProvider, Callable[[], bool]] = {
    LLMProvider.OLLAMA: lambda: bool(settings.OLLAMA_BASE_URL),
    LLMProvider.AWS_BEDROCK: lambda: bool(settings.AWS_BEDROCK_REGION),
    LLMProvider.GROQ: lambda: bool(settings.GROQ_API_KEY),
    LLMProvider.NVIDIA: lambda: bool(settings.NVIDIA_API_KEY),
    LLMProvider.OPENAI: lambda: bool(settings.OPENAI_API_KEY),
    LLMProvider.HUGGINGFACE: lambda: bool(settings.HUGGINGFACE_API_KEY),
    LLMProvider.OPEN_ROUTER: lambda: bool(settings.OPEN_ROUTER_API_KEY),
}


def is_configured(provider: LLMProvider) -> bool:
    return _CHECKS[provider]()
