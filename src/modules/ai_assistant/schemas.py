"""Pydantic v2 request/response schemas for the `ai_assistant` module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.modules.ai_assistant.enums import ChatMessageRole, LLMProvider
from src.modules.ai_assistant.models import Chat, ChatMessage
from src.modules.ai_assistant.validators import (
    MAX_MESSAGE_LENGTH,
    MAX_TITLE_LENGTH,
    validate_message,
    validate_title,
)

# ── Requests ────────────────────────────────────────────────────────────────


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    provider: LLMProvider | None = None
    model: str | None = Field(default=None, max_length=255)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"title": "New Chat", "provider": "ollama", "model": "llama3.1:8b"}
        }
    )

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return validate_title(value) if value is not None else value


class ChatUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LENGTH)

    model_config = ConfigDict(json_schema_extra={"example": {"title": "July Spending Analysis"}})

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return validate_title(value)


class MessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)

    model_config = ConfigDict(
        json_schema_extra={"example": {"message": "How much did I spend on food this month?"}}
    )

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        return validate_message(value)


# ── Responses ───────────────────────────────────────────────────────────────


class ChatResponse(BaseModel):
    id: uuid.UUID
    title: str
    provider: LLMProvider
    model: str
    created_at: datetime
    updated_at: datetime


class ChatListItem(ChatResponse):
    message_count: int


class ChatListResponse(BaseModel):
    items: list[ChatListItem]
    total: int


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: ChatMessageRole
    content: str
    sequence: int
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[ChatMessageResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def to_chat_response(chat: Chat) -> ChatResponse:
    return ChatResponse(
        id=chat.id,
        title=chat.title,
        provider=chat.provider,
        model=chat.model,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def to_chat_list_item(chat: Chat, message_count: int) -> ChatListItem:
    return ChatListItem(**to_chat_response(chat).model_dump(), message_count=message_count)


def to_message_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        sequence=message.sequence,
        created_at=message.created_at,
    )
