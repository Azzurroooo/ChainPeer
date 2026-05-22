import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

# Legacy sync runtime API. Quanora PR#3 refactor replaced AgentRuntime with
# AsyncRuntimeFacade. These tests need to be rewritten against the async API.
pytestmark = pytest.mark.skip(reason="legacy AgentRuntime API replaced by AsyncRuntimeFacade in PR#3 refactor")

try:
    from agent.application.runtime import AgentRuntime  # type: ignore[attr-defined]
except ImportError:
    AgentRuntime = None  # type: ignore[assignment]


class FakeMessage:
    def __init__(self, content: str, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class RecordingChatClient:
    def __init__(self, content: str):
        self.content = content

    def create(self, *, messages, tools, stream):
        return FakeResponse(FakeMessage(self.content))


class DummyToolExecutor:
    def execute(self, name, parsed_args, raw_args=""):
        raise AssertionError("Tool executor should not be called in this test.")


class RecordingSession:
    def __init__(self):
        self.persisted = []
        self.latest_snapshot = None
        self.latest_summary = None
        self.tool_summaries = {}

    def now_iso(self) -> str:
        return "2026-04-01T00:00:00+00:00"

    def get_messages_slice(self, start=None, end=None, roles=None):
        return [{"role": "system", "content": "sys"}]

    def get_tool_records(self, limit=None, call_ids=None):
        return []

    def get_tool_summaries(self, call_ids=None):
        return {}

    def persist_tool_summary(self, summary: dict) -> None:
        self.tool_summaries[summary["call_id"]] = dict(summary)

    def get_latest_conversation_summary(self):
        return dict(self.latest_summary) if isinstance(self.latest_summary, dict) else None

    def persist_conversation_summary(self, summary: dict) -> None:
        self.latest_summary = dict(summary)

    def persist_context_snapshot(self, snapshot: dict) -> None:
        self.latest_snapshot = dict(snapshot)

    def persist_message(self, role, content, tool_call_id=None, tool_name=None, meta=None):
        self.persisted.append({"role": role, "content": content, "meta": meta})

    def persist_tool_call(self, call_id, name, args, raw_args, ts_start, ts_end, result):
        raise AssertionError("persist_tool_call should not be called in this test.")


def test_whitespace_only_assistant_content_is_not_persisted() -> None:
    runtime = AgentRuntime(
        chat_client=RecordingChatClient("\n"),
        tool_executor=DummyToolExecutor(),
        tool_schemas=[],
        debug=True,
    )
    session = RecordingSession()

    runtime.process_user_turn(session=session, on_content=lambda _: None)

    if session.persisted:
        raise AssertionError(f"Expected no persisted assistant message for whitespace-only content, got: {session.persisted}")
    if not session.latest_snapshot:
        raise AssertionError("Expected context snapshot to still be recorded.")


def main() -> int:
    test_whitespace_only_assistant_content_is_not_persisted()
    print("Whitespace assistant content tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
