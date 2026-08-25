"""AWS Bedrock provider adapter.

Explicit `AWS_BEDROCK_ACCESS_KEY_ID`/`AWS_BEDROCK_SECRET_ACCESS_KEY` are
optional — when unset, `ChatBedrockConverse` falls back to boto3's normal
credential chain (environment, shared config, instance role, ...), the same
way the AWS CLI/SDK would in a deployed environment.
"""

from collections.abc import Sequence
from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.core.app_config import settings
from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.providers.base import BaseLLMProvider
from src.modules.ai_assistant.providers.capabilities import (
    ProviderCapabilities,
    resolve_capabilities,
)


class AWSBedrockProvider(BaseLLMProvider):
    name = "aws_bedrock"

    def is_configured(self) -> bool:
        return bool(settings.AWS_BEDROCK_REGION)

    def create_model(
        self, model: str, *, tools: Sequence[BaseTool] | None = None
    ) -> Runnable[LanguageModelInput, AIMessage]:
        kwargs: dict[str, Any] = {
            "model": model,
            "region_name": settings.AWS_BEDROCK_REGION,
            "timeout": settings.AI_LLM_TIMEOUT_SECONDS,
        }
        if settings.AWS_BEDROCK_ACCESS_KEY_ID and settings.AWS_BEDROCK_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.AWS_BEDROCK_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.AWS_BEDROCK_SECRET_ACCESS_KEY
        chat_model = ChatBedrockConverse(**kwargs)
        return chat_model.bind_tools(tools) if tools else chat_model

    def capabilities(self, model: str) -> ProviderCapabilities:
        return resolve_capabilities(LLMProvider.AWS_BEDROCK, model)
