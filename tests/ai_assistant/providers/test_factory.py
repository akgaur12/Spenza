"""Tests for `LLMFactory`: each of the 7 providers wires the right
credentials/base URL to its underlying LangChain class, missing
credentials raise `ProviderUnavailableError`, and an unsupported model
raises `UnsupportedProviderCapabilityError` — all without ever touching a
real network or provider SDK (the underlying LangChain chat-model classes
are monkeypatched to recording stubs).
"""

from typing import Any, cast

import pytest
from langchain_core.tools import BaseTool

from src.core.app_config import settings
from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.exceptions import (
    ProviderUnavailableError,
    UnsupportedProviderCapabilityError,
)
from src.modules.ai_assistant.providers.factory import LLMFactory


class _RecordingChatModel:
    """Records the kwargs it was constructed with; never touches a network."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.bound_tools: object = None

    def bind_tools(self, tools: object) -> "_RecordingChatModel":
        self.bound_tools = tools
        return self


def _recorded(model: object) -> _RecordingChatModel:
    """`LLMFactory.create` is typed to return a plain LangChain `Runnable` —
    this narrows it back to the recording stub these tests monkeypatched
    in, purely for assertions.
    """
    return cast(_RecordingChatModel, model)


def test_openai_provider_wires_api_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import openai_provider

    monkeypatch.setattr(openai_provider, "ChatOpenAI", _RecordingChatModel)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")

    model, capabilities = LLMFactory.create(LLMProvider.OPENAI, "gpt-4.1-mini")
    recording = _recorded(model)

    assert recording.kwargs["model"] == "gpt-4.1-mini"
    assert recording.kwargs["api_key"] == "sk-test"
    assert "base_url" not in recording.kwargs
    assert capabilities.tool_calling is True


def test_groq_provider_wires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import groq_provider

    monkeypatch.setattr(groq_provider, "ChatOpenAI", _RecordingChatModel)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")

    model, _capabilities = LLMFactory.create(LLMProvider.GROQ, "llama-3.1-8b-instant")
    recording = _recorded(model)

    assert recording.kwargs["base_url"] == "https://api.groq.com/openai/v1"
    assert recording.kwargs["api_key"] == "gsk-test"


def test_nvidia_provider_wires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import nvidia_provider

    monkeypatch.setattr(nvidia_provider, "ChatOpenAI", _RecordingChatModel)
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "nvapi-test")

    model, _capabilities = LLMFactory.create(LLMProvider.NVIDIA, "meta/llama-3.1-8b-instruct")
    recording = _recorded(model)

    assert recording.kwargs["base_url"] == "https://integrate.api.nvidia.com/v1"


def test_open_router_provider_wires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import open_router_provider

    monkeypatch.setattr(open_router_provider, "ChatOpenAI", _RecordingChatModel)
    monkeypatch.setattr(settings, "OPEN_ROUTER_API_KEY", "or-test")

    model, _capabilities = LLMFactory.create(LLMProvider.OPEN_ROUTER, "openai/gpt-4.1-mini")
    recording = _recorded(model)

    assert recording.kwargs["base_url"] == "https://openrouter.ai/api/v1"


def test_huggingface_provider_wires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import huggingface_provider

    monkeypatch.setattr(huggingface_provider, "ChatOpenAI", _RecordingChatModel)
    monkeypatch.setattr(settings, "HUGGINGFACE_API_KEY", "hf-test")

    model, _capabilities = LLMFactory.create(
        LLMProvider.HUGGINGFACE, "meta-llama/Llama-3.1-8B-Instruct"
    )
    recording = _recorded(model)

    assert recording.kwargs["base_url"] == "https://router.huggingface.co/v1"


def test_ollama_provider_wires_base_url_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import ollama_provider

    monkeypatch.setattr(ollama_provider, "ChatOllama", _RecordingChatModel)

    model, _capabilities = LLMFactory.create(LLMProvider.OLLAMA, "llama3.1:8b")
    recording = _recorded(model)

    assert recording.kwargs["base_url"] == settings.OLLAMA_BASE_URL
    assert "api_key" not in recording.kwargs


def test_aws_bedrock_provider_wires_region(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import aws_bedrock_provider

    monkeypatch.setattr(aws_bedrock_provider, "ChatBedrockConverse", _RecordingChatModel)
    monkeypatch.setattr(settings, "AWS_BEDROCK_REGION", "us-east-1")

    model, _capabilities = LLMFactory.create(
        LLMProvider.AWS_BEDROCK, "anthropic.claude-3-haiku-20240307-v1:0"
    )
    recording = _recorded(model)

    assert recording.kwargs["region_name"] == "us-east-1"
    assert recording.kwargs["model"] == "anthropic.claude-3-haiku-20240307-v1:0"


def test_unconfigured_provider_raises_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    with pytest.raises(ProviderUnavailableError):
        LLMFactory.create(LLMProvider.OPENAI, "gpt-4.1-mini")


def test_denylisted_model_raises_unsupported_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsupportedProviderCapabilityError):
        LLMFactory.create(LLMProvider.OLLAMA, "nomic-embed-text")


def test_tools_are_bound_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.ai_assistant.providers import openai_provider

    monkeypatch.setattr(openai_provider, "ChatOpenAI", _RecordingChatModel)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")

    fake_tools = cast("list[BaseTool]", [object()])
    model, _capabilities = LLMFactory.create(LLMProvider.OPENAI, "gpt-4.1-mini", tools=fake_tools)
    recording = _recorded(model)

    assert recording.bound_tools == fake_tools
