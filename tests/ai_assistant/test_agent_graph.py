"""Direct agent/runner-level tests, no HTTP layer — multiple sequential
tool calls, a tool that raises, a tool that times out, and cancellation
via a second, concurrent `ChatService.cancel_run` call racing an in-flight
`stream_run`. These use synthetic tools (not the real registry) so
timeouts/failures are trivial to script deterministically.
"""

import asyncio
import uuid
from collections.abc import Callable

from httpx import AsyncClient
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.ai_assistant.agent.runner import AgentRunner, AgentRunResult
from src.modules.ai_assistant.enums import LLMProvider
from src.modules.ai_assistant.repository import ChatMessageRepository, ChatRunRepository
from src.modules.ai_assistant.schemas import ChatCreate, MessageCreate
from src.modules.ai_assistant.service import ChatService
from tests.ai_assistant.fakes import FakeChatModel, FakeTurn
from tests.ai_assistant.helpers import USER_A_SIGNUP, get_user
from tests.conftest import RecordingEmailBackend, register_verified_user


class NoArgs(BaseModel):
    pass


def _make_runner(
    *, tool_timeout_seconds: float = 5.0, agent_timeout_seconds: float = 5.0
) -> AgentRunner:
    return AgentRunner(
        agent_timeout_seconds=agent_timeout_seconds, tool_timeout_seconds=tool_timeout_seconds
    )


async def test_multiple_sequential_tool_calls() -> None:
    calls: list[str] = []

    async def first_handler(**_: object) -> str:
        calls.append("first")
        return '{"step": "first"}'

    async def second_handler(**_: object) -> str:
        calls.append("second")
        return '{"step": "second"}'

    first_tool = StructuredTool.from_function(
        name="first_tool", description="first", args_schema=NoArgs, coroutine=first_handler
    )
    second_tool = StructuredTool.from_function(
        name="second_tool", description="second", args_schema=NoArgs, coroutine=second_handler
    )

    model = FakeChatModel(
        turns=[
            FakeTurn(tool_calls=[{"name": "first_tool", "args": {}, "id": "call_1"}]),
            FakeTurn(tool_calls=[{"name": "second_tool", "args": {}, "id": "call_2"}]),
            FakeTurn(text_chunks=["Done."]),
        ]
    )

    runner = _make_runner()
    result_box: list[AgentRunResult] = []
    events = [
        event
        async for event in runner.stream(
            run_id=uuid.uuid4(),
            chat_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            provider="ollama",
            model_name="fake",
            model=model,
            tools=[first_tool, second_tool],
            messages=[HumanMessage(content="do both things")],
            result_box=result_box,
        )
    ]

    assert calls == ["first", "second"]
    tool_started_names = [e.data["tool"] for e in events if e.event.value == "tool_started"]
    assert tool_started_names == ["first_tool", "second_tool"]
    assert result_box[0].status == "completed"
    assert result_box[0].content == "Done."


async def test_tool_failure_is_reported_and_run_still_completes() -> None:
    async def boom(**_: object) -> str:
        raise ValueError("kaboom")

    boom_tool = StructuredTool.from_function(
        name="boom", description="boom", args_schema=NoArgs, coroutine=boom
    )
    model = FakeChatModel(
        turns=[
            FakeTurn(tool_calls=[{"name": "boom", "args": {}, "id": "call_1"}]),
            FakeTurn(text_chunks=["That tool failed, but here's what I know."]),
        ]
    )

    runner = _make_runner()
    result_box: list[AgentRunResult] = []
    events = [
        event
        async for event in runner.stream(
            run_id=uuid.uuid4(),
            chat_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            provider="ollama",
            model_name="fake",
            model=model,
            tools=[boom_tool],
            messages=[HumanMessage(content="hi")],
            result_box=result_box,
        )
    ]

    tool_result = next(e for e in events if e.event.value == "tool_result")
    assert tool_result.data == {"tool": "boom", "status": "error"}
    assert result_box[0].status == "completed"


async def test_tool_timeout_is_reported_and_run_still_completes() -> None:
    async def slow(**_: object) -> str:
        await asyncio.sleep(10)
        return "too late"

    slow_tool = StructuredTool.from_function(
        name="slow", description="slow", args_schema=NoArgs, coroutine=slow
    )
    model = FakeChatModel(
        turns=[
            FakeTurn(tool_calls=[{"name": "slow", "args": {}, "id": "call_1"}]),
            FakeTurn(text_chunks=["It took too long."]),
        ]
    )

    runner = _make_runner(tool_timeout_seconds=0.1)
    result_box: list[AgentRunResult] = []
    events = [
        event
        async for event in runner.stream(
            run_id=uuid.uuid4(),
            chat_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            provider="ollama",
            model_name="fake",
            model=model,
            tools=[slow_tool],
            messages=[HumanMessage(content="hi")],
            result_box=result_box,
        )
    ]

    tool_result = next(e for e in events if e.event.value == "tool_result")
    assert tool_result.data == {"tool": "slow", "status": "error"}
    assert result_box[0].status == "completed"


async def test_cancel_mid_run_via_service(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: Callable[[FakeChatModel], None],
) -> None:
    """Two DB sessions, mirroring the real HTTP flow: one streams the run,
    the other calls `cancel_run` while the first is paused at a `yield` —
    `AgentRunner`'s cancellation is a level-triggered `asyncio.Event`, so
    requesting cancel while the generator is merely suspended (not
    actively executing) is exactly as valid as a genuinely concurrent
    task racing it, and is far less flaky to test.
    """
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    cancelled_once = False

    async with db_session_factory() as stream_session:
        user = await get_user(stream_session, USER_A_SIGNUP["email"])
        service = ChatService(stream_session)
        chat = await service.create_for_user(
            user, ChatCreate(title=None, provider=LLMProvider.OLLAMA, model="fake")
        )

        install_fake_model(
            FakeChatModel(turns=[FakeTurn(text_chunks=["a", "b", "c", "d"], delay_seconds=0.05)])
        )

        prepared = await service.prepare_run(chat.id, user, MessageCreate(message="Hi"))

        events = []
        async for event in service.stream_run(prepared, user):
            events.append(event)
            if event.event.value == "message_delta" and not cancelled_once:
                cancelled_once = True
                async with db_session_factory() as cancel_session:
                    cancel_user = await get_user(cancel_session, USER_A_SIGNUP["email"])
                    cancel_service = ChatService(cancel_session)
                    await cancel_service.cancel_run(
                        chat.id, prepared.assistant_message.id, cancel_user
                    )

    names = [e.event.value for e in events]
    assert names[-1] == "run_cancelled", names

    async with db_session_factory() as verify_session:
        run = await ChatRunRepository(verify_session).get_by_id(prepared.run.id)
        assert run is not None
        assert run.status.value == "cancelled"
        message = await ChatMessageRepository(verify_session).get_by_id_for_chat(
            prepared.assistant_message.id, chat.id
        )
        assert message is not None
