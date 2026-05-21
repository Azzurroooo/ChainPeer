import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agent.interfaces.cli.chat_cli import ChatCLI


class ClosableEventStream:
    def __init__(self):
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


class FakeRuntime:
    def __init__(self):
        self.stream = ClosableEventStream()
        self.received_token = None

    def run_turn(self, query=None, cancellation_token=None):
        self.received_token = cancellation_token
        return self.stream


class FakeSession:
    pass


@pytest.mark.asyncio
async def test_run_turn_async_closes_event_stream_and_passes_token() -> None:
    runtime = FakeRuntime()
    cli = ChatCLI(runtime=runtime, session=FakeSession())

    await cli._run_turn_async("hello")

    if runtime.stream.closed is not True:
        raise AssertionError("Expected runtime event stream to be closed")
    if runtime.received_token is None:
        raise AssertionError("Expected cancellation token to be passed to runtime")


def test_shutdown_loop_cancels_pending_tasks() -> None:
    loop = asyncio.new_event_loop()
    cli = ChatCLI(runtime=FakeRuntime(), session=FakeSession())

    async def _forever():
        await asyncio.Event().wait()

    try:
        task = loop.create_task(_forever())
        cli._shutdown_loop(loop)
    finally:
        if not loop.is_closed():
            loop.close()

    if not task.cancelled():
        raise AssertionError("Expected pending task to be cancelled during shutdown")
    if not loop.is_closed():
        raise AssertionError("Expected shutdown helper to close the event loop")


def main() -> int:
    asyncio.run(test_run_turn_async_closes_event_stream_and_passes_token())
    test_shutdown_loop_cancels_pending_tasks()
    print("ChatCLI shutdown tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
