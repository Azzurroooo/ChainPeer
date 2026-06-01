import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextBudget, ContextEstimator, ContextManager
from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore


class QueryOnlySession:
    def __init__(self, messages):
        self._messages = [dict(message) for message in messages]
        self.latest_snapshot = None
        self.persisted_tool_summaries = []
        self.persisted_conversation_summaries = []

    async def get_messages_slice(self, start=None, end=None, roles=None):
        messages = [dict(message) for message in self._messages]
        if roles:
            allowed = set(roles)
            messages = [message for message in messages if message.get("role") in allowed]
        return messages[slice(start, end)]

    async def get_tool_records(self, limit=None, call_ids=None):
        raise AssertionError("ContextManager should not read tool records during append-only build")

    async def get_tool_summaries(self, call_ids=None):
        raise AssertionError("ContextManager should not read tool summaries during append-only build")

    async def persist_tool_summary(self, summary: dict) -> None:
        self.persisted_tool_summaries.append(dict(summary))

    async def get_latest_conversation_summary(self):
        raise AssertionError("ContextManager should not read rolling summaries during append-only build")

    async def persist_conversation_summary(self, summary: dict) -> None:
        self.persisted_conversation_summaries.append(dict(summary))

    async def persist_context_snapshot(self, snapshot: dict) -> None:
        self.latest_snapshot = dict(snapshot)


@pytest.mark.asyncio
async def test_context_manager_builds_from_session_queries() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
        {"role": "tool", "tool_call_id": "c1", "content": "tool output"},
    ]
    manager = ContextManager(
        estimator=ContextEstimator(
            ContextBudget(hard_limit_tokens=950, conversation_budget_tokens=900, tool_budget_tokens=900)
        )
    )
    session = QueryOnlySession(session_messages)

    result = await manager.build_messages_async(session=session)

    if result.messages != session_messages:
        raise AssertionError(f"Expected session-backed messages, got: {result.messages}")
    if result.stats.get("persisted_message_count") != 4:
        raise AssertionError(f"Unexpected stats: {result.stats}")
    if "estimated_input_tokens" not in result.stats:
        raise AssertionError(f"Expected estimate in stats, got: {result.stats}")
    if result.stats.get("context_window_tokens") != 258400:
        raise AssertionError(f"Expected Codex-style context window stats, got: {result.stats}")
    if result.stats.get("effective_context_window_tokens") != 245480:
        raise AssertionError(f"Expected effective context window stats, got: {result.stats}")
    if "context_usage_percent" not in result.stats:
        raise AssertionError(f"Expected context usage percent, got: {result.stats}")
    if result.decisions.get("source") != "session_queries":
        raise AssertionError(f"Unexpected decisions: {result.decisions}")
    if result.decisions.get("compact_required") is not False:
        raise AssertionError(f"Unexpected compact decision: {result.decisions}")
    if result.decisions.get("tool_policy_applied") is not False:
        raise AssertionError(f"Expected tool policy disabled, got: {result.decisions}")
    if result.decisions.get("rolling_summary_applied") is not False:
        raise AssertionError(f"Expected rolling summary disabled, got: {result.decisions}")
    if not result.snapshot or len(result.snapshot.tool_messages) != 1:
        raise AssertionError(f"Expected one tool message in snapshot, got: {result.snapshot}")
    if not session.latest_snapshot or session.latest_snapshot.get("message_count") != 4:
        raise AssertionError(f"Expected persisted context snapshot, got: {session.latest_snapshot}")


@pytest.mark.asyncio
async def test_context_manager_appends_pending_messages() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    pending = [{"role": "assistant", "content": "pending reply"}]
    session = QueryOnlySession(session_messages)

    result = await ContextManager().build_messages_async(session=session, pending_messages=pending)

    if result.messages != session_messages + pending:
        raise AssertionError(f"Expected pending overlay appended, got: {result.messages}")
    if result.stats.get("pending_message_count") != 1:
        raise AssertionError(f"Unexpected pending stats: {result.stats}")
    if result.decisions.get("uses_pending_overlay") is not True:
        raise AssertionError(f"Unexpected pending decisions: {result.decisions}")


@pytest.mark.asyncio
async def test_context_manager_build_is_stable_and_has_no_summary_side_effects() -> None:
    session_messages = [{"role": "system", "content": "sys"}]
    for index in range(8):
        session_messages.append({"role": "user", "content": f"user message {index} " + ("x" * 80)})
        session_messages.append({"role": "assistant", "content": f"assistant reply {index} " + ("y" * 80)})
    session = QueryOnlySession(session_messages)
    manager = ContextManager(
        estimator=ContextEstimator(
            ContextBudget(
                hard_limit_tokens=5000,
                conversation_budget_tokens=20,
                tool_budget_tokens=80,
                compact_threshold_tokens=20,
                context_window_tokens=100,
                auto_compact_token_limit=20,
            )
        ),
        hot_message_limit=4,
    )

    first = await manager.build_messages_async(session=session)
    second = await manager.build_messages_async(session=session)

    if first.messages != second.messages or first.messages != session_messages:
        raise AssertionError(f"Expected stable append-only projection, got: {first.messages} / {second.messages}")
    if session.persisted_tool_summaries or session.persisted_conversation_summaries:
        raise AssertionError("Context build should not persist summaries")
    if first.stats.get("summary_message_count") != 0 or first.stats.get("cold_compacted_message_count") != 0:
        raise AssertionError(f"Expected no rolling summary stats, got: {first.stats}")
    if first.decisions.get("compact_recommended") is not True:
        raise AssertionError(f"Expected compact recommendation only, got: {first.decisions}")
    if first.decisions.get("auto_compact_token_limit_reached") is not True:
        raise AssertionError(f"Expected auto compact token limit reached, got: {first.decisions}")
    if first.decisions.get("compact_required") is not False:
        raise AssertionError(f"Did not expect hard-limit compact requirement, got: {first.decisions}")


@pytest.mark.asyncio
async def test_context_manager_new_tool_append_does_not_change_old_tool_content() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "tool_calls": [{"id": "old", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "old", "content": "old fixed model content"},
    ]
    session = QueryOnlySession(session_messages)
    manager = ContextManager()

    first = await manager.build_messages_async(session=session)
    session._messages.extend(
        [
            {"role": "assistant", "tool_calls": [{"id": "new", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "new", "content": "new fixed model content"},
        ]
    )
    second = await manager.build_messages_async(session=session)

    old_first = next(message for message in first.messages if message.get("tool_call_id") == "old")
    old_second = next(message for message in second.messages if message.get("tool_call_id") == "old")
    if old_first != old_second:
        raise AssertionError(f"Expected old tool content to remain fixed, got {old_first} / {old_second}")
    if session.persisted_tool_summaries:
        raise AssertionError(f"Did not expect tool summaries, got: {session.persisted_tool_summaries}")


@pytest.mark.asyncio
async def test_context_manager_persists_lightweight_context_snapshot(tmp_path) -> None:
    session = AsyncJsonlSessionStore(session_dir=str(tmp_path), system_prompt="sys")
    await session.initialize()
    long_output = "large tool output " + ("z" * 5000)
    await session.persist_message(
        "assistant",
        "",
        meta={"tool_calls": [{"id": "call_large", "name": "bash"}]},
    )
    await session.persist_tool_call(
        call_id="call_large",
        name="bash",
        parsed_args={},
        raw_args="{}",
        ts_start=session.now_iso(),
        ts_end=session.now_iso(),
        result_payload=json.dumps({"ok": True, "tool": "bash", "data": long_output}),
    )
    await session.persist_message("tool", "", tool_call_id="call_large", tool_name="bash")

    result = await ContextManager().build_messages_async(session=session)
    meta_path = tmp_path / session.session_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    latest_snapshot = meta.get("latest_context_snapshot")

    if not isinstance(latest_snapshot, dict):
        raise AssertionError(f"Expected latest context snapshot metadata, got: {meta}")
    if "snapshot" in latest_snapshot:
        raise AssertionError(f"Did not expect full snapshot in meta, got: {latest_snapshot.keys()}")
    if latest_snapshot.get("estimated_input_tokens") != result.stats.get("estimated_input_tokens"):
        raise AssertionError(f"Expected lightweight stats to remain, got: {latest_snapshot}")
    if long_output in json.dumps(latest_snapshot, ensure_ascii=False):
        raise AssertionError("Did not expect long tool output in persisted meta snapshot")
    if result.snapshot is None or len(result.snapshot.tool_messages) != 1:
        raise AssertionError(f"Expected in-memory result snapshot to remain available, got: {result.snapshot}")


def main() -> int:
    import asyncio
    import tempfile

    async def _run_all():
        await test_context_manager_builds_from_session_queries()
        await test_context_manager_appends_pending_messages()
        await test_context_manager_build_is_stable_and_has_no_summary_side_effects()
        await test_context_manager_new_tool_append_does_not_change_old_tool_content()
        with tempfile.TemporaryDirectory() as tmp:
            await test_context_manager_persists_lightweight_context_snapshot(Path(tmp))

    asyncio.run(_run_all())
    print("ContextManager tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
