import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextManager
from agent.infrastructure.persistence import JsonlSessionStore


def _make_store(temp_root: Path) -> JsonlSessionStore:
    store = JsonlSessionStore(session_dir=str(temp_root), system_prompt="sys")
    store.ensure_session()
    store.initialize_history()
    return store


def test_context_query_interfaces() -> None:
    temp_root = PROJECT_ROOT / "test" / "__session_context_queries__"
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        store = _make_store(temp_root)
        store.persist_message("user", "hello")
        store.persist_message("assistant", "hi there")
        store.persist_tool_call(
            call_id="call_1",
            name="bash",
            args={"command": "echo hi"},
            raw_args='{"command":"echo hi"}',
            ts_start="2026-04-01T00:00:00+00:00",
            ts_end="2026-04-01T00:00:01+00:00",
            result='{"ok": true, "tool": "bash", "data": {"stdout": "hi", "stderr": "", "exit_code": 0}}',
        )
        store.persist_message("tool", "", tool_call_id="call_1", tool_name="bash")
        store.persist_message(
            "assistant",
            "",
            meta={"tool_calls": [{"id": "call_1", "name": "bash"}]},
        )
        store.persist_message("assistant", "after tool")

        system_message = store.get_system_message()
        if system_message != {"role": "system", "content": "sys"}:
            raise AssertionError(f"Unexpected system message: {system_message}")

        recent = store.get_recent_messages(3)
        expected_recent = [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"ok": true, "tool": "bash", "data": {"stdout": "hi", "stderr": "", "exit_code": 0}}',
            },
            {
                "role": "assistant",
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": '{"command":"echo hi"}'}}],
            },
            {"role": "assistant", "content": "after tool"},
        ]
        if recent != expected_recent:
            raise AssertionError(f"Unexpected recent messages: {recent}")

        assistants = store.get_messages_slice(roles=["assistant"])
        if assistants[-1] != {"role": "assistant", "content": "after tool"}:
            raise AssertionError(f"Unexpected assistant slice: {assistants}")
        if not any(message.get("tool_calls") for message in assistants):
            raise AssertionError(f"Expected assistant tool_calls message in slice: {assistants}")

        tool_records = store.get_tool_records(limit=1)
        if len(tool_records) != 1 or tool_records[0].get("id") != "call_1":
            raise AssertionError(f"Unexpected tool records: {tool_records}")

        filtered_tool_records = store.get_tool_records(call_ids=["call_1"])
        if len(filtered_tool_records) != 1 or filtered_tool_records[0].get("name") != "bash":
            raise AssertionError(f"Unexpected filtered tool records: {filtered_tool_records}")

        if store.get_latest_conversation_summary() is not None:
            raise AssertionError("Expected no conversation summary in Step 1B.")
        if store.get_latest_context_snapshot() is not None:
            raise AssertionError("Expected no context snapshot before Step 2 build.")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_context_snapshot_persistence() -> None:
    temp_root = PROJECT_ROOT / "test" / "__session_context_snapshot__"
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        store = _make_store(temp_root)
        store.persist_message("user", "hello")
        result = ContextManager().build_messages(session=store)
        snapshot = store.get_latest_context_snapshot()
        if not snapshot:
            raise AssertionError("Expected latest context snapshot to be persisted.")
        if snapshot.get("message_count") != len(result.messages):
            raise AssertionError(f"Unexpected persisted snapshot: {snapshot}")
        if "estimated_input_tokens" not in snapshot:
            raise AssertionError(f"Expected estimate fields in snapshot: {snapshot}")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    test_context_query_interfaces()
    test_context_snapshot_persistence()
    print("Session context query tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
