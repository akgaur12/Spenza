"""Domain-specific exceptions for the `ai_assistant` module.

Every exception here subclasses `src.core.exceptions.AppError`, so the
existing global exception handler (`src.core.exception_handlers`) turns it
into the standard `ErrorResponse` envelope with no new wiring needed.
"""

from src.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
)


class ChatNotFoundError(NotFoundError):
    """No chat owned by the current user matches the given identifier."""

    error_code = "CHAT_NOT_FOUND"


class MessageNotFoundError(NotFoundError):
    """No message in this chat matches the given identifier."""

    error_code = "MESSAGE_NOT_FOUND"


class RunNotCancellableError(ConflictError):
    """The run is not currently active and cannot be cancelled."""

    error_code = "AI_RUN_NOT_CANCELLABLE"


class ProviderUnavailableError(ServiceUnavailableError):
    """The selected AI provider is temporarily unavailable."""

    error_code = "AI_PROVIDER_UNAVAILABLE"


class UnsupportedProviderCapabilityError(BadRequestError):
    """The selected provider/model does not support a capability this
    assistant requires (streaming and tool calling are both mandatory).
    """

    error_code = "AI_UNSUPPORTED_CAPABILITY"


class ToolExecutionError(ServiceUnavailableError):
    """A tool call failed or exceeded its timeout while answering."""

    error_code = "AI_TOOL_EXECUTION_FAILED"


class AgentExecutionError(ServiceUnavailableError):
    """The agent failed to produce a response."""

    error_code = "AI_AGENT_EXECUTION_FAILED"


class AgentTimeoutError(ServiceUnavailableError):
    """The agent did not finish within the configured time budget."""

    error_code = "AI_AGENT_TIMEOUT"


class AIAssistantDisabledError(ForbiddenError):
    """The current user has not been granted access to the AI assistant."""

    error_code = "AI_ASSISTANT_DISABLED"


class AIChatRateLimitedError(TooManyRequestsError):
    """The user's per-minute message limit has been reached."""

    error_code = "AI_CHAT_RATE_LIMITED"


class AIChatDailyLimitExceededError(TooManyRequestsError):
    """The user's per-day message limit has been reached."""

    error_code = "AI_CHAT_DAILY_LIMIT_EXCEEDED"


class AIChatMonthlyLimitExceededError(TooManyRequestsError):
    """The user's per-month message limit has been reached."""

    error_code = "AI_CHAT_MONTHLY_LIMIT_EXCEEDED"


class AIChatDailyChatLimitExceededError(TooManyRequestsError):
    """The user's per-day new-chat limit has been reached."""

    error_code = "AI_CHAT_DAILY_CHAT_LIMIT_EXCEEDED"


class AIChatMonthlyChatLimitExceededError(TooManyRequestsError):
    """The user's per-month new-chat limit has been reached."""

    error_code = "AI_CHAT_MONTHLY_CHAT_LIMIT_EXCEEDED"
