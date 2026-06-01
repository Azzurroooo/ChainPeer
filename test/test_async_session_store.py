import shutil
import tempfile
import pytest
import os
import asyncio
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore

@pytest.fixture
def temp_session_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

@pytest.mark.asyncio
async def test_async_session_store_facade(temp_session_dir):
    async_store = AsyncJsonlSessionStore(session_dir=temp_session_dir)
    
    await async_store.initialize()
    
    assert async_store.session_id is not None
    
    # Test persistence
    await async_store.persist_message("user", "Hello World")
    
    # Load and verify
    messages = await async_store.load_messages()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello World"
    
    # Test concurrency isolation informally
    async def write_msgs(role, n):
        for i in range(n):
            await async_store.persist_message(role, f"msg_{i}")
            
    await asyncio.gather(
        write_msgs("assistant", 5),
        write_msgs("system", 5)
    )
    
    messages = await async_store.load_messages()
    assert len(messages) == 11 # 1 user + 5 assistant + 5 system


def test_resolve_session_root_uses_chainpeer_home(monkeypatch, tmp_path):
    chainpeer_home = tmp_path / ".chainpeer"
    monkeypatch.setenv("CHAINPEER_HOME", str(chainpeer_home))

    root = AsyncJsonlSessionStore.resolve_session_root()

    assert root == os.path.abspath(str(chainpeer_home / "sessions"))


def test_resolve_session_root_uses_explicit_session_dir(tmp_path):
    session_dir = tmp_path / "custom_sessions"

    root = AsyncJsonlSessionStore.resolve_session_root(str(session_dir))

    assert root == os.path.abspath(str(session_dir))


@pytest.mark.asyncio
async def test_persist_tool_call_writes_model_content(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("assistant", "", meta={"tool_calls": [{"id": "call_1", "name": "bash"}]})
    await store.persist_tool_call(
        call_id="call_1",
        name="bash",
        parsed_args={"command": "date"},
        raw_args='{"command":"date"}',
        ts_start=store.now_iso(),
        ts_end=store.now_iso(),
        result_payload=json.dumps({"ok": True, "tool": "bash", "data": "raw result"}),
        model_content="fixed model content",
        model_content_format="tool_result_v1",
        model_content_policy={"version": "tool_result_v1"},
        artifact_ref=None,
    )
    await store.persist_message("tool", "", tool_call_id="call_1", tool_name="bash")

    records = await store.get_tool_records(call_ids=["call_1"])
    messages = await store.get_messages_slice()

    assert records[0]["model_content"] == "fixed model content"
    tool_message = next(message for message in messages if message.get("role") == "tool")
    assert tool_message["content"] == "fixed model content"


@pytest.mark.asyncio
async def test_get_messages_slice_legacy_tool_record_fallback(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("assistant", "", meta={"tool_calls": [{"id": "legacy", "name": "bash"}]})
    await store.persist_tool_call(
        call_id="legacy",
        name="bash",
        parsed_args={},
        raw_args="{}",
        ts_start=store.now_iso(),
        ts_end=store.now_iso(),
        result_payload=json.dumps({"ok": True, "tool": "bash", "data": "legacy output"}),
    )
    await store.persist_message("tool", "", tool_call_id="legacy", tool_name="bash")

    messages = await store.get_messages_slice()
    tool_message = next(message for message in messages if message.get("role") == "tool")

    assert "legacy output" in tool_message["content"]


@pytest.mark.asyncio
async def test_manual_compact_appends_boundary_without_rewriting_messages(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "old question")
    await store.persist_message("assistant", "old answer")
    before = await store.load_messages()

    record = await store.compact_context()
    after = await store.load_messages()

    assert after[: len(before)] == before
    assert after[-1]["meta"]["kind"] == "compact_boundary"
    assert after[-1]["meta"]["compact_id"] == record["id"]

    compacted_messages = await store.get_messages_slice()
    assert compacted_messages[0] == {"role": "system", "content": "sys"}
    assert compacted_messages[1]["role"] == "assistant"
    assert compacted_messages[1]["content"].startswith("Context compacted.")
    assert "old question" in compacted_messages[1]["content"]

    await store.persist_message("user", "new question")
    first = await store.get_messages_slice()
    second = await store.get_messages_slice()

    assert first == second
    assert first[-1] == {"role": "user", "content": "new question"}


@pytest.mark.asyncio
async def test_sampling_usage_and_auto_compact_window_meta(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()

    usage = {
        "sampling_kind": "assistant",
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "cache_hit_rate": 0.4,
        "output_tokens": 25,
        "total_tokens": 125,
        "context_usage_percent": 0.1,
        "effective_context_window_tokens": 1000,
    }
    await store.persist_sampling_usage(usage)
    await store.update_auto_compact_window_from_usage(usage)

    latest = await store.get_latest_sampling_usage()
    window = await store.get_auto_compact_window()

    assert latest["input_tokens"] == 100
    assert latest["cached_input_tokens"] == 40
    assert window["ordinal"] == 1
    assert window["prefill_input_tokens"] == 100
    assert window["prefill_source"] == "server"

    await store.start_next_auto_compact_window()
    next_window = await store.get_auto_compact_window()

    assert next_window["ordinal"] == 2
    assert next_window["prefill_input_tokens"] is None


def main() -> int:
    async def _run_all():
        with tempfile.TemporaryDirectory() as tmp:
            await test_async_session_store_facade(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_persist_tool_call_writes_model_content(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_get_messages_slice_legacy_tool_record_fallback(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_manual_compact_appends_boundary_without_rewriting_messages(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_sampling_usage_and_auto_compact_window_meta(tmp)

    asyncio.run(_run_all())
    print("AsyncJsonlSessionStore tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
