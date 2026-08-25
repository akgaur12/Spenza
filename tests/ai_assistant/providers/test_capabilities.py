"""Tests for capability resolution: best-effort `True` by default, `False`
for denylisted model-name substrings, and that the assistant rejects
anything missing a required capability.
"""

import pytest

from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.exceptions import UnsupportedProviderCapabilityError
from src.modules.ai_assistant.providers.capabilities import (
    ensure_required_capabilities,
    resolve_capabilities,
)


def test_unknown_model_is_best_effort_capable() -> None:
    capabilities = resolve_capabilities(LLMProvider.OPENAI, "gpt-4.1-mini")
    assert capabilities.streaming is True
    assert capabilities.tool_calling is True


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        (LLMProvider.HUGGINGFACE, "sentence-transformers/all-MiniLM-embed"),
        (LLMProvider.NVIDIA, "nvidia/nv-embedqa-rerank"),
        (LLMProvider.OLLAMA, "nomic-embed-text"),
        (LLMProvider.GROQ, "whisper-large-v3"),
    ],
)
def test_denylisted_models_lose_tool_calling(provider: LLMProvider, model: str) -> None:
    capabilities = resolve_capabilities(provider, model)
    assert capabilities.tool_calling is False
    assert capabilities.streaming is True


def test_ensure_required_capabilities_raises_for_denylisted_model() -> None:
    capabilities = resolve_capabilities(LLMProvider.OLLAMA, "nomic-embed-text")
    with pytest.raises(UnsupportedProviderCapabilityError):
        ensure_required_capabilities(capabilities, LLMProvider.OLLAMA, "nomic-embed-text")


def test_ensure_required_capabilities_passes_for_capable_model() -> None:
    capabilities = resolve_capabilities(LLMProvider.OPENAI, "gpt-4.1-mini")
    ensure_required_capabilities(capabilities, LLMProvider.OPENAI, "gpt-4.1-mini")
