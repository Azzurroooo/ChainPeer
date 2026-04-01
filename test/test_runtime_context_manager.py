import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.runtime import AgentRuntime
from agent.application.services import ContextManager


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
    def __init__(self):
        self.calls = []

    def create(self, *, messages, tools, stream):
        self.calls.append({"messages": messages, "tools": tools, "stream": stream})
        return FakeResponse(FakeMessage("assistant reply"))


class DummyToolExecutor:
    def execute(self, name, parsed_args, raw_args=""):
        raise AssertionError("Tool executor should not be called in this test.")


class RecordingSession:
    def __init__(self):
        self.persisted = []
        self.stored_messages = [{"role": "system", "content": "session-source"}]

    def now_iso(self) -> str:
        return "2026-04-01T00:00:00+00:00"

    def get_messages_slice(self, start=None, end=None, roles=None):
        messages = [dict(message) for message in self.stored_messages]
        if roles:
            allowed = set(roles)
            messages = [message for message in messages if message.get("role") in allowed]
        return messages[slice(start, end)]

    def persist_message(self, role, content, tool_call_id=None, tool_name=None, meta=None):
        payload = {
            "role": role,
            "content": content,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "meta": meta,
        }
        self.persisted.append(payload)
        if role == "assistant" and meta and meta.get("tool_calls"):
            self.stored_messages.append({"role": "assistant", "tool_calls": meta["tool_calls"]})
            return
        if role == "tool":
            self.stored_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
            return
        self.stored_messages.append({"role": role, "content": content})

    def persist_tool_call(self, call_id, name, args, raw_args, ts_start, ts_end, result):
        raise AssertionError("persist_tool_call should not be called in this test.")


def test_runtime_uses_session_backed_context_manager_messages() -> None:
    chat_client = RecordingChatClient()
    runtime = AgentRuntime(
        chat_client=chat_client,
        tool_executor=DummyToolExecutor(),
        tool_schemas=[],
        context_manager=ContextManager(),
        debug=True,
    )
    session = RecordingSession()
    seen_content = []

    runtime.process_user_turn(session=session, on_content=seen_content.append)

    sent_messages = chat_client.calls[0]["messages"]
    if sent_messages != [{"role": "system", "content": "session-source"}]:
        raise AssertionError(f"Expected runtime to send session-backed messages, got: {sent_messages}")
    if session.persisted[-1]["content"] != "assistant reply":
        raise AssertionError(f"Expected assistant reply persisted to session, got: {session.persisted}")
    if session.stored_messages[-1] != {"role": "assistant", "content": "assistant reply"}:
        raise AssertionError(f"Expected stored messages updated, got: {session.stored_messages}")


def main() -> int:
    test_runtime_uses_session_backed_context_manager_messages()
    print("Runtime ContextManager integration tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
