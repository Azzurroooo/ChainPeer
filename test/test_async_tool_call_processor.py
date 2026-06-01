import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agent.application.runtime.async_tool_call_processor import AsyncToolCallProcessor
from agent.application.runtime.cancellation import CancellationTokenSource
from agent.domain import ParsedToolCall
from agent.domain.events import ToolCallStartedEvent, ToolResultEvent
from agent.domain.jobs import ToolExecutionResult


class FakeToolExecutor:
    def __init__(self):
        self.received_args = None

    def is_async_tool(self, name: str) -> bool:
        return True

    async def execute_async(self, name: str, args: dict, raw_args: str | None = None):
        self.received_args = dict(args)
        return ToolExecutionResult(status="ok", result_str="done")


class FakeSession:
    session_id = "session_1"

    def __init__(self):
        self.persisted_tool_calls = []
        self.persisted_messages = []

    def now_iso(self):
        return "2026-05-21T00:00:00Z"

    async def persist_tool_call(self, *args, **kwargs):
        self.persisted_tool_calls.append((args, kwargs))

    async def persist_message(self, *args, **kwargs):
        self.persisted_messages.append((args, kwargs))


@pytest.mark.asyncio
async def test_bash_cancellation_token_is_not_persisted_in_tool_args() -> None:
    executor = FakeToolExecutor()
    session = FakeSession()
    processor = AsyncToolCallProcessor(tool_executor=executor)
    cancel_source = CancellationTokenSource()
    call = ParsedToolCall(
        call_id="call_1",
        name="bash",
        raw_args='{"command":"date"}',
    )

    events = [
        event
        async for event in processor.execute(
            session=session,
            tool_calls=[call],
            cancellation_token=cancel_source.token,
        )
    ]

    if "_cancellation_token" not in executor.received_args:
        raise AssertionError(f"Expected execution args to include cancellation token, got: {executor.received_args}")
    if not any(isinstance(event, ToolResultEvent) for event in events):
        raise AssertionError(f"Expected tool result event, got: {events}")
    result_events = [event for event in events if isinstance(event, ToolResultEvent)]
    if result_events[-1].status != "completed":
        raise AssertionError(f"Expected completed tool result, got: {result_events[-1]}")
    persisted_args = session.persisted_tool_calls[0][0][2]
    if persisted_args != {"command": "date"}:
        raise AssertionError(f"Expected clean persisted args, got: {persisted_args}")
    if not session.persisted_tool_calls[0][1].get("model_content"):
        raise AssertionError(f"Expected normalized model content, got: {session.persisted_tool_calls[0]}")


@pytest.mark.asyncio
async def test_invalid_tool_args_emit_failed_result_without_started_event() -> None:
    processor = AsyncToolCallProcessor(tool_executor=FakeToolExecutor())
    session = FakeSession()
    call = ParsedToolCall(
        call_id="call_bad",
        name="bash",
        raw_args="{bad json",
    )

    events = [event async for event in processor.execute(session=session, tool_calls=[call], turn_id="turn_1")]

    if any(isinstance(event, ToolCallStartedEvent) for event in events):
        raise AssertionError(f"Did not expect started event for invalid args, got: {events}")

    result_events = [event for event in events if isinstance(event, ToolResultEvent)]
    if len(result_events) != 1:
        raise AssertionError(f"Expected one result event, got: {events}")
    result = result_events[0]
    if result.status != "failed" or result.error_type != "ToolArgsJSONError":
        raise AssertionError(f"Expected failed parse result, got: {result}")
    if result.turn_id != "turn_1":
        raise AssertionError(f"Expected turn_id to be propagated, got: {result.turn_id}")


@pytest.mark.asyncio
async def test_successful_tool_does_not_require_job_service() -> None:
    processor = AsyncToolCallProcessor(tool_executor=FakeToolExecutor())
    session = FakeSession()
    call = ParsedToolCall(
        call_id="call_1",
        name="demo_tool",
        raw_args='{"value":"x"}',
    )

    events = [event async for event in processor.execute(session=session, tool_calls=[call])]

    if not any(isinstance(event, ToolCallStartedEvent) for event in events):
        raise AssertionError(f"Expected started event, got: {events}")
    result_events = [event for event in events if isinstance(event, ToolResultEvent)]
    if len(result_events) != 1 or result_events[0].status != "completed":
        raise AssertionError(f"Expected completed result, got: {events}")
    if len(session.persisted_tool_calls) != 1:
        raise AssertionError("Expected tool call to be persisted directly")
    args, kwargs = session.persisted_tool_calls[0]
    persisted_result = args[-1]
    if '"ok": true' not in persisted_result or '"tool": "demo_tool"' not in persisted_result:
        raise AssertionError(f"Expected standardized tool payload, got: {persisted_result}")
    if kwargs.get("model_content_format") != "tool_result_v1":
        raise AssertionError(f"Expected model_content_format, got: {kwargs}")
    if kwargs.get("artifact_ref") is not None:
        raise AssertionError(f"Expected artifact_ref None, got: {kwargs}")


def main() -> int:
    import asyncio

    asyncio.run(test_bash_cancellation_token_is_not_persisted_in_tool_args())
    asyncio.run(test_invalid_tool_args_emit_failed_result_without_started_event())
    asyncio.run(test_successful_tool_does_not_require_job_service())
    print("AsyncToolCallProcessor tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
