import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.runtime import AgentRuntime


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

    def now_iso(self) -> str:
        return "2026-04-01T00:00:00+00:00"

    def get_messages_slice(self, start=None, end=None, roles=None):
        return [{"role": "system", "content": "sys"}]

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


def main() -> int:
    test_whitespace_only_assistant_content_is_not_persisted()
    print("Whitespace assistant content tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
