import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agent.application.services import ContextBudget, ContextEstimator, ContextManager, ToolContextPolicy


class QueryOnlySession:
    def __init__(self, messages):
        self._messages = [dict(message) for message in messages]
        self.latest_snapshot = None
        self.latest_summary = None
        self.persisted_summaries = []
        self.tool_records = {}
        self.tool_summaries = {}

    async def get_messages_slice(self, start=None, end=None, roles=None):
        messages = [dict(message) for message in self._messages]
        if roles:
            allowed = set(roles)
            messages = [message for message in messages if message.get("role") in allowed]
        return messages[slice(start, end)]

    async def get_tool_records(self, limit=None, call_ids=None):
        records = [dict(record) for record in self.tool_records.values()]
        if call_ids:
            allowed = set(call_ids)
            records = [record for record in records if record.get("id") in allowed]
        if limit is not None:
            records = records[-limit:]
        return records

    async def get_tool_summaries(self, call_ids=None):
        if not call_ids:
            return {key: dict(value) for key, value in self.tool_summaries.items()}
        allowed = set(call_ids)
        return {key: dict(value) for key, value in self.tool_summaries.items() if key in allowed}

    async def persist_tool_summary(self, summary: dict) -> None:
        self.tool_summaries[summary["call_id"]] = dict(summary)

    async def get_latest_conversation_summary(self):
        return dict(self.latest_summary) if isinstance(self.latest_summary, dict) else None

    async def persist_conversation_summary(self, summary: dict) -> None:
        self.latest_summary = dict(summary)
        self.persisted_summaries.append(dict(summary))

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
    session.tool_records = {
        "c1": {
            "id": "c1",
            "name": "bash",
            "result": {"ok": True, "tool": "bash", "data": "tool output"},
        }
    }

    result = await manager.build_messages_async(session=session)

    expected_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
        {"role": "tool", "tool_call_id": "c1", "content": '{"tool": "bash", "ok": null}'},
    ]
    if result.messages != expected_messages:
        raise AssertionError(f"Expected session-backed messages, got: {result.messages}")
    if (result.stats or {}).get("persisted_message_count") != 4:
        raise AssertionError(f"Unexpected stats: {result.stats}")
    if "estimated_input_tokens" not in (result.stats or {}):
        raise AssertionError(f"Expected estimate in stats, got: {result.stats}")
    if (result.decisions or {}).get("source") != "session_queries":
        raise AssertionError(f"Unexpected decisions: {result.decisions}")
    if (result.decisions or {}).get("compact_required") is not False:
        raise AssertionError(f"Unexpected compact decision: {result.decisions}")
    if "over_conversation_budget" not in (result.decisions or {}):
        raise AssertionError(f"Expected independent conversation budget decision, got: {result.decisions}")
    snapshot = result.snapshot
    if snapshot is None or (snapshot.system_message or {}).get("role") != "system":
        raise AssertionError(f"Expected system message snapshot, got: {snapshot}")
    if len(snapshot.tool_messages) != 1:
        raise AssertionError(f"Expected one tool message in snapshot, got: {snapshot.tool_messages}")
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
    if (result.stats or {}).get("pending_message_count") != 1:
        raise AssertionError(f"Unexpected pending stats: {result.stats}")
    if (result.decisions or {}).get("uses_pending_overlay") is not True:
        raise AssertionError(f"Unexpected pending decisions: {result.decisions}")


@pytest.mark.asyncio
async def test_context_manager_compacts_only_cold_conversation_zone() -> None:
    session_messages = [{"role": "system", "content": "sys"}]
    for index in range(1, 7):
        session_messages.append({"role": "user", "content": f"user message {index} with enough text to raise the estimate"})
        session_messages.append({"role": "assistant", "content": f"assistant reply {index} with enough text to raise the estimate"})
    session = QueryOnlySession(session_messages)
    manager = ContextManager(
        estimator=ContextEstimator(
            ContextBudget(hard_limit_tokens=2000, conversation_budget_tokens=20, tool_budget_tokens=80)
        ),
        hot_message_limit=4,
    )

    result = await manager.build_messages_async(session=session)

    if not (result.decisions or {}).get("rolling_summary_applied"):
        raise AssertionError(f"Expected rolling summary to be applied, got: {result.decisions}")
    if len(session.persisted_summaries) != 1:
        raise AssertionError(f"Expected a persisted summary, got: {session.persisted_summaries}")
    if not result.snapshot or len(result.snapshot.summary_messages) != 1:
        raise AssertionError(f"Expected summary message in snapshot, got: {result.snapshot}")
    if result.stats.get("cold_compacted_message_count", 0) <= 0:
        raise AssertionError(f"Expected compacted cold message count, got: {result.stats}")
    if not any(message.get("content", "").startswith("Conversation summary:") for message in result.messages):
        raise AssertionError(f"Expected rendered summary message, got: {result.messages}")
    system_messages = [message for message in result.messages if message.get("role") == "system"]
    if system_messages != [{"role": "system", "content": "sys"}]:
        raise AssertionError(f"Expected only the leading system message to remain system-scoped, got: {system_messages}")
    summary_messages = [message for message in result.messages if message.get("content", "").startswith("Conversation summary:")]
    if len(summary_messages) != 1 or summary_messages[0].get("role") != "assistant":
        raise AssertionError(f"Expected summary to be rendered as a single assistant message, got: {summary_messages}")
    tail = result.messages[-4:]
    expected_tail = session_messages[-4:]
    if tail != expected_tail:
        raise AssertionError(f"Expected hot zone preserved, got tail={tail}")


@pytest.mark.asyncio
async def test_context_manager_applies_tool_temperature_policy() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "tool_calls": [{"id": "call_old", "type": "function", "function": {"name": "search_web", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_old", "content": "placeholder"},
        {"role": "assistant", "tool_calls": [{"id": "call_mid", "type": "function", "function": {"name": "fetch_web_page", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_mid", "content": "placeholder"},
        {"role": "assistant", "tool_calls": [{"id": "call_new", "type": "function", "function": {"name": "fetch_web_page", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_new", "content": "placeholder"},
    ]
    session = QueryOnlySession(session_messages)
    session.tool_records = {
        "call_old": {
            "id": "call_old",
            "name": "search_web",
            "result": {"ok": True, "tool": "search_web", "data": "x" * 2000},
        },
        "call_mid": {
            "id": "call_mid",
            "name": "fetch_web_page",
            "result": {"ok": True, "tool": "fetch_web_page", "data": "m" * 2000},
        },
        "call_new": {
            "id": "call_new",
            "name": "fetch_web_page",
            "result": {"ok": True, "tool": "fetch_web_page", "data": "y" * 2000},
        },
    }
    result = await ContextManager().build_messages_async(session=session)
    tool_messages = [message for message in result.messages if message.get("role") == "tool"]
    old_tool = next(message for message in tool_messages if message.get("tool_call_id") == "call_old")
    new_tool = next(message for message in tool_messages if message.get("tool_call_id") == "call_new")

    if len(old_tool.get("content", "")) >= len(new_tool.get("content", "")):
        raise AssertionError(f"Expected older tool content to be more compact, got old={len(old_tool.get('content', ''))} new={len(new_tool.get('content', ''))}")
    if "call_old" not in session.tool_summaries:
        raise AssertionError(f"Expected a persisted tool summary for cold/warm tool calls, got: {session.tool_summaries}")


@pytest.mark.asyncio
async def test_context_manager_prioritizes_hot_tool_budget() -> None:
    session_messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "tool_calls": [{"id": "call_old", "type": "function", "function": {"name": "search_web", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_old", "content": "placeholder"},
        {"role": "assistant", "tool_calls": [{"id": "call_new", "type": "function", "function": {"name": "fetch_web_page", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_new", "content": "placeholder"},
    ]
    session = QueryOnlySession(session_messages)
    session.tool_records = {
        "call_old": {
            "id": "call_old",
            "name": "search_web",
            "result": {"ok": True, "tool": "search_web", "data": "x" * 4000},
        },
        "call_new": {
            "id": "call_new",
            "name": "fetch_web_page",
            "result": {"ok": True, "tool": "fetch_web_page", "data": "y" * 4000},
        },
    }
    manager = ContextManager(
        estimator=ContextEstimator(ContextBudget(tool_budget_tokens=15, conversation_budget_tokens=1000, hard_limit_tokens=2000)),
        tool_context_policy=ToolContextPolicy(hot_batch_limit=1, warm_batch_limit=0),
    )

    result = await manager.build_messages_async(session=session)
    tool_messages = [message for message in result.messages if message.get("role") == "tool"]
    old_tool = next(message for message in tool_messages if message.get("tool_call_id") == "call_old")
    new_tool = next(message for message in tool_messages if message.get("tool_call_id") == "call_new")

    if not new_tool.get("content"):
        raise AssertionError(f"Expected hot tool content to receive budget first, got: {new_tool}")
    if len(new_tool.get("content", "")) < len(old_tool.get("content", "")):
        raise AssertionError(
            f"Expected hot tool to preserve at least as much content as cold tool, got old={len(old_tool.get('content', ''))}, new={len(new_tool.get('content', ''))}"
        )


def main() -> int:
    import asyncio
    async def _run_all():
        await test_context_manager_builds_from_session_queries()
        await test_context_manager_appends_pending_messages()
        await test_context_manager_compacts_only_cold_conversation_zone()
        await test_context_manager_applies_tool_temperature_policy()
        await test_context_manager_prioritizes_hot_tool_budget()
    asyncio.run(_run_all())
    print("ContextManager tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
