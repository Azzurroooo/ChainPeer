import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextManager


class QueryOnlySession:
    def __init__(self, messages):
        self._messages = [dict(message) for message in messages]

    def get_messages_slice(self, start=None, end=None, roles=None):
        messages = [dict(message) for message in self._messages]
        if roles:
            allowed = set(roles)
            messages = [message for message in messages if message.get("role") in allowed]
        return messages[slice(start, end)]


def test_context_manager_builds_from_session_queries() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
        {"role": "tool", "tool_call_id": "c1", "content": "tool output"},
    ]

    result = ContextManager().build_messages(session=QueryOnlySession(session_messages))

    if result.messages != session_messages:
        raise AssertionError(f"Expected session-backed messages, got: {result.messages}")
    if (result.stats or {}).get("persisted_message_count") != 4:
        raise AssertionError(f"Unexpected stats: {result.stats}")
    if (result.decisions or {}).get("source") != "session_queries":
        raise AssertionError(f"Unexpected decisions: {result.decisions}")
    snapshot = result.snapshot
    if snapshot is None or (snapshot.system_message or {}).get("role") != "system":
        raise AssertionError(f"Expected system message snapshot, got: {snapshot}")
    if len(snapshot.tool_messages) != 1:
        raise AssertionError(f"Expected one tool message in snapshot, got: {snapshot.tool_messages}")


def test_context_manager_appends_pending_messages() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    pending = [{"role": "assistant", "content": "pending reply"}]

    result = ContextManager().build_messages(session=QueryOnlySession(session_messages), pending_messages=pending)

    if result.messages != session_messages + pending:
        raise AssertionError(f"Expected pending overlay appended, got: {result.messages}")
    if (result.stats or {}).get("pending_message_count") != 1:
        raise AssertionError(f"Unexpected pending stats: {result.stats}")
    if (result.decisions or {}).get("uses_pending_overlay") is not True:
        raise AssertionError(f"Unexpected pending decisions: {result.decisions}")


def main() -> int:
    test_context_manager_builds_from_session_queries()
    test_context_manager_appends_pending_messages()
    print("ContextManager tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
