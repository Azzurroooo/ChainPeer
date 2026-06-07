import shutil
import tempfile
import pytest
import os
import asyncio
import sys
import json
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore
from agent.infrastructure.persistence.session_files import SessionFiles

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
    session_base = Path(temp_session_dir) / async_store.session_id
    meta = json.loads((session_base / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "2.0"
    assert (session_base / "messages.jsonl").exists()
    assert (session_base / "tool_calls.jsonl").exists()
    removed_files = ["conversation_" + "summaries.jsonl", "tool_call_" + "summaries.jsonl"]
    for removed in removed_files:
        assert not (session_base / removed).exists()
    assert not (session_base / ("snap" + "shots")).exists()
    assert not (session_base / "compactions.jsonl").exists()
    
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


def test_session_files_read_jsonl_waits_for_active_writer(tmp_path):
    path = tmp_path / "messages.jsonl"
    files = SessionFiles()

    with files._get_lock_for_path(str(path)):
        path.write_text('{"role": "user"', encoding="utf-8")
        read_result = []

        thread = threading.Thread(
            target=lambda: read_result.extend(files.read_jsonl(str(path))),
        )
        thread.start()
        time.sleep(0.1)

        assert thread.is_alive()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(', "content": "complete"}\n')

    thread.join(timeout=2)

    assert not thread.is_alive()
    assert read_result == [{"role": "user", "content": "complete"}]


def test_session_files_load_json_waits_for_active_writer(tmp_path):
    path = tmp_path / "meta.json"
    files = SessionFiles()

    with files._get_lock_for_path(str(path)):
        path.write_text('{"schema_version": ', encoding="utf-8")
        read_result = []

        thread = threading.Thread(
            target=lambda: read_result.append(files.load_json(str(path))),
        )
        thread.start()
        time.sleep(0.1)

        assert thread.is_alive()
        with path.open("a", encoding="utf-8") as handle:
            handle.write('"2.0"}')

    thread.join(timeout=2)

    assert not thread.is_alive()
    assert read_result == [{"schema_version": "2.0"}]


def test_session_files_load_json_reports_corrupt_json(tmp_path):
    path = tmp_path / "meta.json"
    path.write_text("{", encoding="utf-8")
    files = SessionFiles()

    with pytest.raises(ValueError, match="Corrupted JSON file"):
        files.load_json(str(path))


def test_session_files_write_json_removes_tmp_on_replace_failure(monkeypatch, tmp_path):
    path = tmp_path / "meta.json"
    files = SessionFiles()
    real_replace = os.replace

    def fail_after_tmp(src, dst):
        if str(dst) == str(path):
            raise OSError("replace failed")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_after_tmp)

    with pytest.raises(OSError, match="replace failed"):
        files.write_json(str(path), {"schema_version": "2.0"})

    leftovers = list(tmp_path.glob("meta.json.*.tmp"))
    assert leftovers == []


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
async def test_get_messages_slice_recovers_missing_tool_message_from_record(temp_session_dir):
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
        model_content="recovered model content",
        model_content_format="tool_result_v1",
        model_content_policy={"version": "tool_result_v1"},
        artifact_ref=None,
    )

    messages = await store.get_messages_slice()

    assert messages == [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command":"date"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "recovered model content"},
    ]


@pytest.mark.asyncio
async def test_get_messages_slice_matches_numeric_tool_ids_as_strings(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("assistant", "", meta={"tool_calls": [{"id": 123, "name": "bash"}]})
    await store.persist_tool_call(
        call_id="123",
        name="bash",
        parsed_args={"command": "date"},
        raw_args='{"command":"date"}',
        ts_start=store.now_iso(),
        ts_end=store.now_iso(),
        result_payload=json.dumps({"ok": True, "tool": "bash", "data": "raw result"}),
        model_content="numeric id content",
        model_content_format="tool_result_v1",
        model_content_policy={"version": "tool_result_v1"},
        artifact_ref=None,
    )

    messages = await store.get_messages_slice()

    assert messages[1]["tool_calls"][0]["id"] == "123"
    assert messages[2] == {"role": "tool", "tool_call_id": "123", "content": "numeric id content"}


@pytest.mark.asyncio
async def test_get_messages_slice_uses_projection_cache_until_files_change(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "first")

    calls = {"messages": 0, "tools": 0, "compactions": 0}
    original_messages = store._msg_repo.load_messages
    original_tools = store._tool_repo.load_tool_calls
    original_compactions = store._compaction_repo.load_compactions

    def load_messages():
        calls["messages"] += 1
        return original_messages()

    def load_tools():
        calls["tools"] += 1
        return original_tools()

    def load_compactions():
        calls["compactions"] += 1
        return original_compactions()

    store._msg_repo.load_messages = load_messages
    store._tool_repo.load_tool_calls = load_tools
    store._compaction_repo.load_compactions = load_compactions

    first = await store.get_messages_slice()
    first[0]["content"] = "mutated"
    second = await store.get_messages_slice()

    assert second[0] == {"role": "system", "content": "sys"}
    assert calls == {"messages": 1, "tools": 1, "compactions": 1}

    await store.persist_message("user", "second")
    third = await store.get_messages_slice()

    assert third[-1] == {"role": "user", "content": "second"}
    assert calls == {"messages": 2, "tools": 2, "compactions": 2}


@pytest.mark.asyncio
async def test_get_messages_slice_rejects_tool_record_without_model_content(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("assistant", "", meta={"tool_calls": [{"id": "legacy", "name": "bash"}]})
    session_base = Path(temp_session_dir) / store.session_id
    legacy_record = {
        "id": "legacy",
        "ts_start": store.now_iso(),
        "ts_end": store.now_iso(),
        "name": "bash",
        "args": {},
        "raw_args": "{}",
        "result": {"ok": True, "tool": "bash", "data": "legacy output"},
    }
    with (session_base / "tool_calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(legacy_record, ensure_ascii=False) + "\n")
    await store.persist_message("tool", "", tool_call_id="legacy", tool_name="bash")

    with pytest.raises(ValueError, match="missing model_content"):
        await store.get_messages_slice()


@pytest.mark.asyncio
async def test_persist_tool_call_requires_model_content(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()

    with pytest.raises(ValueError, match="model_content"):
        await store.persist_tool_call(
            call_id="call_missing",
            name="bash",
            parsed_args={},
            raw_args="{}",
            ts_start=store.now_iso(),
            ts_end=store.now_iso(),
            result_payload=json.dumps({"ok": True, "tool": "bash", "data": "raw"}),
            model_content="",
        )


@pytest.mark.asyncio
async def test_legacy_session_schema_is_rejected(temp_session_dir):
    session_id = "legacy_session"
    session_base = Path(temp_session_dir) / session_id
    session_base.mkdir(parents=True)
    (session_base / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "session_id": session_id,
                "updated_at": "2026-01-01T00:00:00+00:00",
                "message_count": 0,
                "tool_call_count": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, session_id=session_id)
    with pytest.raises(ValueError, match="Unsupported legacy session schema"):
        await store.initialize()


@pytest.mark.asyncio
async def test_persist_compaction_appends_boundary_without_rewriting_messages(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "old question")
    await store.persist_message("assistant", "old answer")
    before = await store.load_messages()

    record = await store.persist_compaction(
        {
            "id": "compact_1",
            "created_at": store.now_iso(),
            "policy_version": "compact_boundary_v2",
            "source": {
                "message_start_index": 0,
                "message_end_index_exclusive": len(before),
                "tool_call_ids": [],
            },
            "handoff_message": {
                "role": "assistant",
                "content": "Context compacted.\n\n- old question\n- old answer",
            },
        }
    )
    after = await store.load_messages()
    session_base = Path(temp_session_dir) / store.session_id

    assert after[: len(before)] == before
    assert (session_base / "compactions.jsonl").exists()
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
async def test_orphan_compaction_record_does_not_compact_context(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "keep this question")
    session_base = Path(temp_session_dir) / store.session_id
    orphan = {
        "id": "orphan_compact",
        "created_at": store.now_iso(),
        "handoff_message": {"role": "assistant", "content": "orphan handoff"},
    }
    with (session_base / "compactions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(orphan, ensure_ascii=False) + "\n")

    messages = await store.get_messages_slice()
    latest = await store.get_latest_compaction()

    assert latest is None
    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "keep this question"},
    ]


@pytest.mark.asyncio
async def test_unmatched_compact_boundary_does_not_truncate_context(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "before broken boundary")
    await store.persist_message("assistant", "", meta={"kind": "compact_boundary", "compact_id": "missing"})
    await store.persist_message("user", "after broken boundary")

    messages = await store.get_messages_slice()
    latest = await store.get_latest_compaction()

    assert latest is None
    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "before broken boundary"},
        {"role": "user", "content": "after broken boundary"},
    ]


@pytest.mark.asyncio
async def test_invalid_compaction_record_does_not_truncate_context(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "before invalid compact")
    session_base = Path(temp_session_dir) / store.session_id
    invalid = {
        "id": "invalid_compact",
        "created_at": store.now_iso(),
        "handoff_message": {"role": "assistant", "content": None},
    }
    with (session_base / "compactions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(invalid, ensure_ascii=False) + "\n")
    await store.persist_message(
        "assistant",
        "",
        meta={"kind": "compact_boundary", "compact_id": "invalid_compact"},
    )
    await store.persist_message("user", "after invalid compact")

    messages = await store.get_messages_slice()
    latest = await store.get_latest_compaction()

    assert latest is None
    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "before invalid compact"},
        {"role": "user", "content": "after invalid compact"},
    ]


@pytest.mark.asyncio
async def test_latest_valid_compact_boundary_survives_newer_broken_boundary(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "old compacted question")
    record = await store.persist_compaction(
        {
            "id": "compact_1",
            "created_at": store.now_iso(),
            "policy_version": "compact_boundary_v2",
            "source": {
                "message_start_index": 0,
                "message_end_index_exclusive": 1,
                "tool_call_ids": [],
            },
            "handoff_message": {
                "role": "assistant",
                "content": "Context compacted.\n\n- old compacted question",
            },
        }
    )
    await store.persist_message("user", "after valid compact")
    await store.persist_message("assistant", "", meta={"kind": "compact_boundary", "compact_id": "missing"})
    await store.persist_message("user", "after broken boundary")

    messages = await store.get_messages_slice()
    latest = await store.get_latest_compaction()

    assert latest is not None
    assert latest["id"] == record["id"]
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"].startswith("Context compacted.")
    assert {"role": "user", "content": "old compacted question"} not in messages
    assert messages[-2:] == [
        {"role": "user", "content": "after valid compact"},
        {"role": "user", "content": "after broken boundary"},
    ]


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

    await store.persist_compaction({"handoff_message": {"role": "assistant", "content": "handoff"}})
    next_window = await store.get_auto_compact_window()

    assert next_window["ordinal"] == 2
    assert next_window["prefill_input_tokens"] is None


@pytest.mark.asyncio
async def test_auto_compact_window_ignores_invalid_usage_tokens(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()

    await store.update_auto_compact_window_from_usage({"input_tokens": "bad"})

    window = await store.get_auto_compact_window()
    assert window["ordinal"] == 1
    assert window["prefill_input_tokens"] is None
    assert window["prefill_source"] is None


@pytest.mark.asyncio
async def test_update_model_persists_session_meta(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, model="old-model", system_prompt="sys")
    await store.initialize()

    await store.update_model("new-model")

    session_base = Path(temp_session_dir) / store.session_id
    meta = json.loads((session_base / "meta.json").read_text(encoding="utf-8"))
    assert store.model == "new-model"
    assert meta["model"] == "new-model"


@pytest.mark.asyncio
async def test_resume_repairs_stale_meta_counts(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "hello")
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
    )

    session_base = Path(temp_session_dir) / store.session_id
    meta_path = session_base / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["message_count"] = 0
    meta["tool_call_count"] = 0
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    resumed = AsyncJsonlSessionStore(session_dir=temp_session_dir, session_id=store.session_id)
    await resumed.initialize()

    repaired = json.loads(meta_path.read_text(encoding="utf-8"))
    assert repaired["message_count"] == 3
    assert repaired["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_resume_repairs_invalid_meta_counts(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()
    await store.persist_message("user", "hello")

    session_base = Path(temp_session_dir) / store.session_id
    meta_path = session_base / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["message_count"] = "bad"
    meta["tool_call_count"] = "also bad"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    resumed = AsyncJsonlSessionStore(session_dir=temp_session_dir, session_id=store.session_id)
    await resumed.initialize()

    repaired = json.loads(meta_path.read_text(encoding="utf-8"))
    assert repaired["message_count"] == 2
    assert repaired["tool_call_count"] == 0


@pytest.mark.asyncio
async def test_resume_normalizes_auto_compact_window_meta(temp_session_dir):
    store = AsyncJsonlSessionStore(session_dir=temp_session_dir, system_prompt="sys")
    await store.initialize()

    session_base = Path(temp_session_dir) / store.session_id
    meta_path = session_base / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["auto_compact_window"] = {"ordinal": "bad", "prefill_input_tokens": "also bad"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    resumed = AsyncJsonlSessionStore(session_dir=temp_session_dir, session_id=store.session_id)
    await resumed.initialize()

    repaired = json.loads(meta_path.read_text(encoding="utf-8"))
    assert repaired["auto_compact_window"] == {
        "ordinal": 1,
        "prefill_input_tokens": None,
        "prefill_source": None,
    }


def main() -> int:
    async def _run_all():
        with tempfile.TemporaryDirectory() as tmp:
            await test_async_session_store_facade(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_persist_tool_call_writes_model_content(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_get_messages_slice_recovers_missing_tool_message_from_record(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_get_messages_slice_matches_numeric_tool_ids_as_strings(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_get_messages_slice_uses_projection_cache_until_files_change(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_get_messages_slice_rejects_tool_record_without_model_content(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_persist_tool_call_requires_model_content(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_legacy_session_schema_is_rejected(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_persist_compaction_appends_boundary_without_rewriting_messages(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_orphan_compaction_record_does_not_compact_context(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_unmatched_compact_boundary_does_not_truncate_context(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_invalid_compaction_record_does_not_truncate_context(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_latest_valid_compact_boundary_survives_newer_broken_boundary(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_sampling_usage_and_auto_compact_window_meta(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_auto_compact_window_ignores_invalid_usage_tokens(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_update_model_persists_session_meta(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_resume_repairs_stale_meta_counts(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_resume_repairs_invalid_meta_counts(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            await test_resume_normalizes_auto_compact_window_meta(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            test_session_files_read_jsonl_waits_for_active_writer(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            test_session_files_load_json_waits_for_active_writer(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            test_session_files_load_json_reports_corrupt_json(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch = pytest.MonkeyPatch()
            try:
                test_session_files_write_json_removes_tmp_on_replace_failure(monkeypatch, Path(tmp))
            finally:
                monkeypatch.undo()

    asyncio.run(_run_all())
    print("AsyncJsonlSessionStore tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
