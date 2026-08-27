"""`chat_router`: the AI expense assistant's chat/message API.

Every route requires authentication via `CurrentUser`. Chats are private
user data — ownership is always derived from `CurrentUser`, never accepted
from the request body/path, mirroring `expenses/router.py`'s design rule.

`POST .../messages` is the one route that talks to an LLM provider. Access
and rate limiting for it are per-user and opt-in — enforced by
`ChatService`/`AIAssistantPermissionService` against `ai_assistant_
permissions` (see `permissions.service`), not a route-level slowapi
decorator: a disabled user has no IP-keyed rate to limit, and each user's
limit is independently configurable by an admin. It's also the only route
that returns `text/event-stream` instead of the standard `SuccessResponse`
envelope.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from src.core.responses import SuccessResponse
from src.modules.ai_assistant.dependencies import get_chat_service
from src.modules.ai_assistant.schemas import (
    ChatCreate,
    ChatListResponse,
    ChatResponse,
    ChatUpdate,
    MessageCreate,
    MessageListResponse,
    to_chat_list_item,
    to_chat_response,
    to_message_response,
)
from src.modules.ai_assistant.service import ChatService
from src.modules.ai_assistant.streaming.sse import sse_response
from src.modules.users.dependencies import CurrentUser

chat_router = APIRouter(prefix="/api/v1/chats", tags=["chats"])


@chat_router.post(
    "",
    response_model=SuccessResponse[ChatResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new AI assistant chat",
)
async def create_chat(
    data: ChatCreate,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SuccessResponse[ChatResponse]:
    chat = await chat_service.create_for_user(current_user, data)
    return SuccessResponse(message="Chat created", data=to_chat_response(chat))


@chat_router.get(
    "",
    response_model=SuccessResponse[ChatListResponse],
    summary="List the current user's chats, most recently updated first",
)
async def list_chats(
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[ChatListResponse]:
    rows, total = await chat_service.list_for_user(
        current_user, search=search, page=page, page_size=page_size
    )
    return SuccessResponse(
        message="OK",
        data=ChatListResponse(
            items=[to_chat_list_item(chat, count) for chat, count in rows], total=total
        ),
    )


@chat_router.get(
    "/{chat_id}",
    response_model=SuccessResponse[ChatResponse],
    summary="Get one of the current user's own chats",
)
async def get_chat(
    chat_id: uuid.UUID,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SuccessResponse[ChatResponse]:
    chat = await chat_service.get_for_user(chat_id, current_user)
    return SuccessResponse(message="OK", data=to_chat_response(chat))


@chat_router.patch(
    "/{chat_id}",
    response_model=SuccessResponse[ChatResponse],
    summary="Rename one of the current user's own chats",
)
async def rename_chat(
    chat_id: uuid.UUID,
    data: ChatUpdate,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SuccessResponse[ChatResponse]:
    chat = await chat_service.rename_for_user(chat_id, current_user, data)
    return SuccessResponse(message="Chat renamed", data=to_chat_response(chat))


@chat_router.delete(
    "/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete one of the current user's own chats",
)
async def delete_chat(
    chat_id: uuid.UUID,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> None:
    await chat_service.delete_for_user(chat_id, current_user)


@chat_router.get(
    "/{chat_id}/messages",
    response_model=SuccessResponse[MessageListResponse],
    summary="List a chat's messages in chronological order",
)
async def list_messages(
    chat_id: uuid.UUID,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SuccessResponse[MessageListResponse]:
    messages, total = await chat_service.list_messages(
        chat_id, current_user, page=page, page_size=page_size
    )
    total_pages = -(-total // page_size) if total else 0
    return SuccessResponse(
        message="OK",
        data=MessageListResponse(
            items=[to_message_response(m) for m in messages],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        ),
    )


@chat_router.post(
    "/{chat_id}/messages",
    summary="Send a message and stream the assistant's response over SSE",
    description=(
        "Persists the message, then streams the agent's response as "
        "`text/event-stream`. See the module documentation for the 9 named "
        "SSE events (`run_started`, `message_started`, `tool_started`, "
        "`tool_result`, `message_delta`, `message_completed`, "
        "`run_completed`, `run_failed`, `run_cancelled`)."
    ),
)
async def send_message(
    chat_id: uuid.UUID,
    data: MessageCreate,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    prepared = await chat_service.prepare_run(chat_id, current_user, data)
    events = chat_service.stream_run(prepared, current_user)
    return sse_response(events)


@chat_router.post(
    "/{chat_id}/messages/{message_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel an in-progress assistant response",
)
async def cancel_message(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> None:
    await chat_service.cancel_run(chat_id, message_id, current_user)
