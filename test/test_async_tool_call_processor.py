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
from agent.domain.events import ToolResultEvent
from agent.domain.jobs import JobHandle, JobRecord, ToolExecutionResult


class FakeToolExecutor:
    def __init__(self):
        self.received_args = None

    def is_async_tool(self, name: str) -> bool:
        return True

    async def execute_async(self, name: str, args: dict, raw_args: str | None = None):
        self.received_args = dict(args)
        return ToolExecutionResult(status="ok", result_str="done")


class FakeJobService:
    def __init__(self):
        self.output = ""
        self.job = None

    def create_job(self, session_id, request_id, tool_call_id, tool_name, metadata=None):
        self.job = JobRecord(
            job_id="job_1",
            session_id=session_id,
            request_id=request_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status="pending",
            metadata=metadata or {},
        )
        return JobHandle(job_id="job_1", status="pending", output_ref=None)

    def update_status(self, job_id, status, error=None, reason=None):
        self.job.status = status
        if error:
            self.job.metadata["error"] = error

    def append_output(self, job_id, content, stream_type="stdout"):
        self.output += content

    def read_output(self, job_id):
        return self.output, len(self.output)

    def get_job(self, job_id):
        return self.job


class FakeSession:
    session_id = "session_1"

    def __init__(self):
        self.persisted_tool_calls = []
        self.persisted_messages = []

    def now_iso(self):
        return "2026-05-21T00:00:00Z"

    async def persist_tool_call(self, *args):
        self.persisted_tool_calls.append(args)

    async def persist_message(self, *args, **kwargs):
        self.persisted_messages.append((args, kwargs))


@pytest.mark.asyncio
async def test_bash_cancellation_token_is_not_persisted_in_tool_args() -> None:
    executor = FakeToolExecutor()
    session = FakeSession()
    processor = AsyncToolCallProcessor(tool_executor=executor, job_service=FakeJobService())
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
    persisted_args = session.persisted_tool_calls[0][2]
    if persisted_args != {"command": "date"}:
        raise AssertionError(f"Expected clean persisted args, got: {persisted_args}")


def main() -> int:
    import asyncio

    asyncio.run(test_bash_cancellation_token_is_not_persisted_in_tool_args())
    print("AsyncToolCallProcessor tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
