"""Capability metadata for LLM providers/models.

`streaming` and `tool_calling` are required by this assistant (see
`ensure_required_capabilities`); `structured_output` is tracked but not
gate-enforced in this phase — nothing here calls `.with_structured_output()`
yet.

All 7 providers' underlying transports support streaming and tool calling in
general, so live per-model capability probing against 7 external APIs isn't
worth the latency/complexity. Instead, a small denylist of known-bad
model-name substrings downgrades `tool_calling` for specific models (e.g.
embedding-only models exposed through an otherwise chat-capable API);
anything else is treated as best-effort `True`, logged once so a genuinely
incompatible model surfaces in logs rather than silently misbehaving.
"""

from dataclasses import dataclass

from src.core.logger import get_logger
from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.exceptions import UnsupportedProviderCapabilityError

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    streaming: bool
    tool_calling: bool
    structured_output: bool


# Model-name substrings (matched case-insensitively) known not to support
# tool calling despite the provider's API otherwise advertising it.
_TOOL_CALLING_DENYLIST: dict[LLMProvider, tuple[str, ...]] = {
    LLMProvider.HUGGINGFACE: ("embed", "whisper", "bge-", "clip"),
    LLMProvider.NVIDIA: ("embed", "rerank", "retrieval"),
    LLMProvider.OPEN_ROUTER: ("embed",),
    LLMProvider.OLLAMA: ("embed", "bge-", "minilm"),
    LLMProvider.GROQ: ("whisper",),
}


def resolve_capabilities(provider: LLMProvider, model: str) -> ProviderCapabilities:
    """Best-effort capability resolution for `provider`/`model`. Every
    provider here is assumed to support streaming (all 7 adapters use
    streaming-capable LangChain chat models). `tool_calling` is `False`
    only for models on the provider's denylist.
    """
    denylist = _TOOL_CALLING_DENYLIST.get(provider, ())
    model_lower = model.lower()
    tool_calling = not any(bad in model_lower for bad in denylist)
    if tool_calling:
        logger.debug("ai.capabilities.best_effort", provider=provider.value, model=model)
    else:
        logger.warning("ai.capabilities.tool_calling_denied", provider=provider.value, model=model)
    return ProviderCapabilities(streaming=True, tool_calling=tool_calling, structured_output=True)


def ensure_required_capabilities(
    capabilities: ProviderCapabilities, provider: LLMProvider, model: str
) -> None:
    """This assistant requires both streaming and tool calling — reject
    anything that can't do both rather than degrading silently.
    """
    if not capabilities.streaming or not capabilities.tool_calling:
        raise UnsupportedProviderCapabilityError(
            f"{provider.value}/{model} does not support the capabilities this "
            "assistant requires (streaming and tool calling)."
        )
