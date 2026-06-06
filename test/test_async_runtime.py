import pytest
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.runtime.async_runtime_facade import AsyncRuntimeFacade
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.domain import ParsedToolCall
from agent.domain.events import (
    AssistantDeltaEvent, 
    AssistantMessageCompletedEvent, 
    ContextBuiltEvent,
    ToolRequestedEvent,
    ToolResultEvent,
    TokenStatsUpdatedEvent,
    TurnStartedEvent,
    TurnCompletedEvent,
    TurnCancelledEvent,
    TurnFailedEvent
)
from agent.application.runtime.cancellation import CancellationTokenSource

@pytest.mark.asyncio
async def test_async_turn_runner_stream():
    mock_client = AsyncMock()
    
    # Mock stream response
    async def mock_stream(*args, **kwargs):
        class MockDelta:
            def __init__(self, content):
                self.content = content
                self.tool_calls = None
        class MockChoice:
            def __init__(self, content):
                self.delta = MockDelta(content)
        class MockChunk:
            def __init__(self, content):
                self.choices = [MockChoice(content)]
                
        yield MockChunk("Hello ")
        yield MockChunk("World!")
        
    mock_client.stream = mock_stream
    
    mock_processor = MagicMock()
    mock_processor.execute_tool_calls = MagicMock()
    
    mock_parser = MagicMock()
    
    # We must mock consume_async_stream because AsyncTurnRunner uses it
    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        await on_content_async("Hello ")
        await on_content_async("World!")
        return "Hello World!", []
    mock_parser.consume_async_stream = mock_consume
    
    mock_context = MagicMock()
    mock_context_async_method = AsyncMock()
    mock_context_async_method.return_value = MagicMock(messages=[], stats={}, decisions={})
    mock_context.build_messages_async = mock_context_async_method
    mock_context.select_active_skills_for_turn = None
    
    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"
    mock_session.persist_message = AsyncMock()
    
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=mock_processor,
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context
    )
    
    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)
        
    assert len(events) == 5
    assert isinstance(events[0], ContextBuiltEvent)
    assert isinstance(events[1], AssistantDeltaEvent)
    assert events[1].text == "Hello "
    assert isinstance(events[2], AssistantDeltaEvent)
    assert events[2].text == "World!"
    assert isinstance(events[3], AssistantMessageCompletedEvent)
    assert events[3].content_chars == len("Hello World!")
    assert isinstance(events[4], TurnCompletedEvent)


@pytest.mark.asyncio
async def test_async_turn_runner_yields_delta_before_stream_completes():
    mock_client = AsyncMock()
    mock_client.stream = MagicMock()

    delta_sent = asyncio.Event()
    finish_stream = asyncio.Event()

    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        await on_content_async("partial")
        delta_sent.set()
        await finish_stream.wait()
        return "partial done", []

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], stats={}, decisions={}))
    mock_context.select_active_skills_for_turn = None

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"
    mock_session.persist_message = AsyncMock()

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = []

    async def collect_events():
        async for event in runner.run_turn(mock_session):
            events.append(event)

    task = asyncio.create_task(collect_events())
    await asyncio.wait_for(delta_sent.wait(), timeout=1)
    await asyncio.sleep(0)

    assert any(isinstance(event, AssistantDeltaEvent) and event.text == "partial" for event in events)
    assert not any(isinstance(event, AssistantMessageCompletedEvent) for event in events)

    finish_stream.set()
    await asyncio.wait_for(task, timeout=1)
    assert any(isinstance(event, AssistantMessageCompletedEvent) for event in events)

@pytest.mark.asyncio
async def test_async_turn_runner_cancellation():
    mock_client = AsyncMock()
    
    async def mock_stream(*args, **kwargs):
        yield MagicMock()
        await asyncio.sleep(0.1) # Simulate delay
        
    mock_client.stream = mock_stream
    
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=MagicMock(),
        tool_schemas=[],
        context_manager=MagicMock()
    )
    
    source = CancellationTokenSource()
    source.cancel("User cancelled")
    
    events = []
    async for event in runner.run_turn(MagicMock(), cancellation_token=source.token):
        events.append(event)
        
    assert len(events) == 1
    assert isinstance(events[0], TurnCancelledEvent)
    assert events[0].reason == "User cancelled"


@pytest.mark.asyncio
async def test_async_turn_runner_stream_cancelled_error_is_cancelled_event():
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    mock_parser = MagicMock()

    async def mock_consume(*args, **kwargs):
        raise asyncio.CancelledError("stream cancelled")

    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], decisions={}))
    mock_context.select_active_skills_for_turn = None

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context
    )

    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)

    assert len(events) == 2
    assert isinstance(events[0], ContextBuiltEvent)
    assert isinstance(events[1], TurnCancelledEvent)
    assert events[1].reason == "stream cancelled"
    assert not any(isinstance(event, TurnFailedEvent) for event in events)


@pytest.mark.asyncio
async def test_async_turn_runner_cancelled_error_prefers_token_reason():
    mock_client = AsyncMock()
    mock_client.stream = MagicMock()

    source = CancellationTokenSource()

    mock_parser = MagicMock()

    async def mock_consume(*args, **kwargs):
        source.cancel("User interrupted")
        raise asyncio.CancelledError()

    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], stats={}, decisions={}))
    mock_context.select_active_skills_for_turn = None

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = [event async for event in runner.run_turn(mock_session, cancellation_token=source.token)]

    assert isinstance(events[-1], TurnCancelledEvent)
    assert events[-1].reason == "User interrupted"
    assert not any(isinstance(event, TurnFailedEvent) for event in events)


@pytest.mark.asyncio
async def test_async_runtime_facade_emits_turn_started_first():
    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.persisted = []

        async def initialize(self):
            return None

        async def persist_message(self, role, content, **kwargs):
            self.persisted.append((role, content, kwargs))

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

    class FakeRunner:
        async def run_turn(self, session, cancellation_token=None, turn_id=""):
            yield TurnCompletedEvent(turn_id=turn_id)

    session = FakeSession()
    facade = AsyncRuntimeFacade(turn_runner=FakeRunner(), session_store=session)

    events = [event async for event in facade.run_turn(query="hello")]

    assert isinstance(events[0], TurnStartedEvent)
    assert events[0].session_id == "session_1"
    assert events[0].user_message_chars == len("hello")
    assert events[0].turn_id
    assert events[1].turn_id == events[0].turn_id
    assert session.persisted == [("user", "hello", {})]


@pytest.mark.asyncio
async def test_async_runtime_facade_initializes_session_once_for_concurrent_turns():
    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.initialize_calls = 0
            self.persisted = []

        async def initialize(self):
            self.initialize_calls += 1
            await asyncio.sleep(0)

        async def persist_message(self, role, content, **kwargs):
            self.persisted.append((role, content, kwargs))

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

    class FakeRunner:
        async def run_turn(self, session, cancellation_token=None, turn_id=""):
            yield TurnCompletedEvent(turn_id=turn_id)

    session = FakeSession()
    facade = AsyncRuntimeFacade(turn_runner=FakeRunner(), session_store=session)

    async def run_query(query: str):
        return [event async for event in facade.run_turn(query=query)]

    first_events, second_events = await asyncio.gather(run_query("first"), run_query("second"))

    assert session.initialize_calls == 1
    assert isinstance(first_events[0], TurnStartedEvent)
    assert isinstance(second_events[0], TurnStartedEvent)
    assert len(session.persisted) == 2


@pytest.mark.asyncio
async def test_async_runtime_facade_manual_compact_uses_runner():
    class FakeSession:
        async def initialize(self):
            return None

    class FakeRunner:
        def __init__(self):
            self.called = None

        async def compact_context(self, session, reason="manual", phase="manual"):
            self.called = (session, reason, phase)
            return {"id": "compact_1"}

    session = FakeSession()
    runner = FakeRunner()
    facade = AsyncRuntimeFacade(turn_runner=runner, session_store=session)

    record = await facade.compact_context(reason="manual")

    assert record == {"id": "compact_1"}
    assert runner.called == (session, "manual", "manual")


@pytest.mark.asyncio
async def test_async_runtime_facade_set_model_updates_runner_and_session():
    class FakeSession:
        def __init__(self):
            self.model = "old-model"

        async def initialize(self):
            return None

        async def update_model(self, model):
            self.model = model

    class FakeRunner:
        def __init__(self):
            self.model = "old-model"

        def set_model(self, model):
            self.model = model
            return True

    session = FakeSession()
    runner = FakeRunner()
    facade = AsyncRuntimeFacade(turn_runner=runner, session_store=session)

    result = await facade.set_model("new-model")

    assert result == {"runtime": True, "session": True}
    assert runner.model == "new-model"
    assert session.model == "new-model"


@pytest.mark.asyncio
async def test_async_turn_runner_emits_tool_requested_before_tool_execution():
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    calls = [
        ({"content": "Need tool", "calls": [ParsedToolCall(call_id="call_1", name="bash", raw_args='{"command":"date"}')]}),
        ({"content": "Done", "calls": []}),
    ]

    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        item = calls.pop(0)
        await on_content_async(item["content"])
        return item["content"], item["calls"]

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], stats={}, decisions={}))
    mock_context.select_active_skills_for_turn = None

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.persisted = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def persist_message(self, *args, **kwargs):
            self.persisted.append((args, kwargs))

    async def execute(*args, **kwargs):
        yield ToolResultEvent(
            tool_call_id="call_1",
            tool_name="bash",
            status="completed",
            turn_id=kwargs.get("turn_id", ""),
        )

    mock_processor = MagicMock()
    mock_processor.execute = execute

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=mock_processor,
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = []
    async for event in runner.run_turn(FakeSession(), turn_id="turn_1"):
        events.append(event)

    requested_index = next(index for index, event in enumerate(events) if isinstance(event, ToolRequestedEvent))
    result_index = next(index for index, event in enumerate(events) if isinstance(event, ToolResultEvent))
    assert requested_index < result_index
    assert events[requested_index].args_preview == '{"command":"date"}'
    assert events[requested_index].turn_id == "turn_1"


@pytest.mark.asyncio
async def test_async_turn_runner_fails_after_tool_persist_failure():
    mock_client = AsyncMock()

    class EmptyStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    def mock_stream(*args, **kwargs):
        return EmptyStream()

    mock_client.stream = MagicMock(side_effect=mock_stream)

    call = ParsedToolCall(call_id="call_1", name="bash", raw_args='{"command":"date"}')

    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        await on_content_async("Need tool")
        return "Need tool", [call]

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], stats={}, decisions={}))
    mock_context.select_active_skills_for_turn = None

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.persisted = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def persist_message(self, *args, **kwargs):
            self.persisted.append((args, kwargs))

    async def execute(*args, **kwargs):
        yield ToolResultEvent(
            tool_call_id="call_1",
            tool_name="bash",
            status="failed",
            error_type="OSError",
            result='{"ok":false}',
            turn_id=kwargs.get("turn_id", ""),
        )
        raise RuntimeError("Failed to persist tool result for call_1: disk full")

    mock_processor = MagicMock()
    mock_processor.execute = execute

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=mock_processor,
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = [event async for event in runner.run_turn(FakeSession(), turn_id="turn_1")]

    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(tool_results) == 1
    assert tool_results[0].status == "failed"
    assert tool_results[0].error_type == "OSError"
    assert isinstance(events[-1], TurnFailedEvent)
    assert events[-1].error_type == "RuntimeError"
    assert "Failed to persist tool result" in events[-1].error
    assert mock_client.stream.call_count == 1


@pytest.mark.asyncio
async def test_async_turn_runner_emits_and_persists_sampling_usage():
    mock_client = AsyncMock()
    mock_client.stream = MagicMock()

    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=25,
        total_tokens=125,
        prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
    )

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = AsyncMock(return_value=("Done", [], usage))

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(
        return_value=MagicMock(
            messages=[],
            stats={
                "context_window_tokens": 258400,
                "effective_context_window_tokens": 245480,
            },
            decisions={},
        )
    )
    mock_context.select_active_skills_for_turn = None

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.usages = []
            self.window_updates = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def persist_message(self, *args, **kwargs):
            return None

        async def persist_sampling_usage(self, usage):
            self.usages.append(dict(usage))

        async def update_auto_compact_window_from_usage(self, usage):
            self.window_updates.append(dict(usage))

    session = FakeSession()
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = [event async for event in runner.run_turn(session)]
    token_event = next(event for event in events if isinstance(event, TokenStatsUpdatedEvent))

    assert token_event.stats["input_tokens"] == 100
    assert token_event.stats["cached_input_tokens"] == 40
    assert token_event.stats["cache_hit_rate"] == 0.4
    assert token_event.stats["context_usage_percent"] == 100 / 245480
    assert session.usages[-1]["output_tokens"] == 25
    assert session.window_updates[-1]["input_tokens"] == 100


@pytest.mark.asyncio
async def test_async_turn_runner_usage_persistence_failure_does_not_fail_turn():
    mock_client = AsyncMock()
    mock_client.stream = MagicMock()

    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    mock_parser = MagicMock()
    mock_parser.consume_async_stream = AsyncMock(return_value=("Done", [], usage))

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(
        return_value=MagicMock(
            messages=[],
            stats={"context_window_tokens": 1000, "effective_context_window_tokens": 900},
            decisions={},
        )
    )
    mock_context.select_active_skills_for_turn = None

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.messages = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def persist_message(self, *args, **kwargs):
            self.messages.append((args, kwargs))

        async def persist_sampling_usage(self, usage):
            raise OSError("meta write failed")

        async def update_auto_compact_window_from_usage(self, usage):
            raise OSError("window write failed")

    session = FakeSession()
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = [event async for event in runner.run_turn(session)]

    assert any(isinstance(event, TokenStatsUpdatedEvent) for event in events)
    assert any(isinstance(event, AssistantMessageCompletedEvent) for event in events)
    assert isinstance(events[-1], TurnCompletedEvent)
    assert not any(isinstance(event, TurnFailedEvent) for event in events)
    assert session.messages == [(("assistant", "Done"), {})]


@pytest.mark.asyncio
async def test_async_turn_runner_usage_tolerates_bad_context_stats():
    mock_client = AsyncMock()
    mock_client.stream = MagicMock()

    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    mock_parser = MagicMock()
    mock_parser.consume_async_stream = AsyncMock(return_value=("Done", [], usage))

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(
        return_value=MagicMock(
            messages=[],
            stats={"context_window_tokens": "bad", "effective_context_window_tokens": 0},
            decisions={},
        )
    )
    mock_context.select_active_skills_for_turn = None

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.usages = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def persist_message(self, *args, **kwargs):
            return None

        async def persist_sampling_usage(self, usage):
            self.usages.append(dict(usage))

        async def update_auto_compact_window_from_usage(self, usage):
            return None

    session = FakeSession()
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = [event async for event in runner.run_turn(session)]

    token_event = next(event for event in events if isinstance(event, TokenStatsUpdatedEvent))
    assert token_event.stats["input_tokens"] == 12
    assert token_event.stats["effective_context_window_tokens"] == 245480
    assert session.usages[-1]["context_window_tokens"] == 258400
    assert any(isinstance(event, AssistantMessageCompletedEvent) for event in events)
    assert not any(isinstance(event, TurnFailedEvent) for event in events)


@pytest.mark.asyncio
async def test_async_turn_runner_auto_compacts_before_sampling():
    class FakeChatClient:
        def __init__(self):
            self.created = 0
            self.streamed = 0

        async def create(self, messages, tools=None, cancellation_token=None):
            self.created += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="LLM handoff"))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        def stream(self, *args, **kwargs):
            self.streamed += 1
            return EmptyStream()

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.compactions = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def load_messages(self):
            return [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]

        async def get_tool_records(self, *args, **kwargs):
            return []

        async def get_latest_compaction(self):
            return None

        async def persist_compaction(self, record):
            self.compactions.append(dict(record))
            return dict(record)

        async def persist_sampling_usage(self, usage):
            return None

        async def persist_message(self, *args, **kwargs):
            return None

    first_context = MagicMock(
        messages=[{"role": "user", "content": "hello"}],
        stats={"context_window_tokens": 1000, "effective_context_window_tokens": 950},
        decisions={"auto_compact_token_limit_reached": True},
    )
    second_context = MagicMock(
        messages=[{"role": "assistant", "content": "LLM handoff"}],
        stats={"context_window_tokens": 1000, "effective_context_window_tokens": 950},
        decisions={},
    )
    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(side_effect=[first_context, second_context])
    mock_context.select_active_skills_for_turn = None

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = AsyncMock(return_value=("", [], None))

    chat_client = FakeChatClient()
    session = FakeSession()
    runner = AsyncTurnRunner(
        chat_client=chat_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = [event async for event in runner.run_turn(session)]

    assert chat_client.created == 1
    assert chat_client.streamed == 1
    assert len(session.compactions) == 1
    assert session.compactions[0]["strategy"] == "llm_inline"
    assert session.compactions[0]["reason"] == "auto"
    assert session.compactions[0]["phase"] == "pre_sampling"
    assert session.compactions[0]["handoff_message"]["content"] == "LLM handoff"
    assert sum(isinstance(event, ContextBuiltEvent) for event in events) == 2


def main() -> int:
    asyncio.run(test_async_turn_runner_stream())
    asyncio.run(test_async_turn_runner_yields_delta_before_stream_completes())
    asyncio.run(test_async_turn_runner_cancellation())
    asyncio.run(test_async_turn_runner_stream_cancelled_error_is_cancelled_event())
    asyncio.run(test_async_turn_runner_cancelled_error_prefers_token_reason())
    asyncio.run(test_async_runtime_facade_emits_turn_started_first())
    asyncio.run(test_async_runtime_facade_initializes_session_once_for_concurrent_turns())
    asyncio.run(test_async_runtime_facade_manual_compact_uses_runner())
    asyncio.run(test_async_runtime_facade_set_model_updates_runner_and_session())
    asyncio.run(test_async_turn_runner_emits_tool_requested_before_tool_execution())
    asyncio.run(test_async_turn_runner_fails_after_tool_persist_failure())
    asyncio.run(test_async_turn_runner_emits_and_persists_sampling_usage())
    asyncio.run(test_async_turn_runner_usage_persistence_failure_does_not_fail_turn())
    asyncio.run(test_async_turn_runner_usage_tolerates_bad_context_stats())
    asyncio.run(test_async_turn_runner_auto_compacts_before_sampling())
    print("Async runtime tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
