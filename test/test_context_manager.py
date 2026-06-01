import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextBudget, ContextEstimator, ContextManager

class QueryOnlySession:
    def __init__(self, messages):
        self._messages = [dict(message) for message in messages]

    async def get_messages_slice(self, start=None, end=None, roles=None):
        messages = [dict(message) for message in self._messages]
        if roles:
            allowed = set(roles)
            messages = [message for message in messages if message.get("role") in allowed]
        return messages[slice(start, end)]


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
    for key in ("tool_policy_applied", "rolling_summary_applied", "rolling_summary_generated"):
        if key in result.decisions:
            raise AssertionError(f"Did not expect legacy decision key {key}, got: {result.decisions}")


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
    for key in ("summary_message_count", "cold_compacted_message_count", "hot_tool_message_count"):
        if key in first.stats:
            raise AssertionError(f"Did not expect legacy stat key {key}, got: {first.stats}")
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


def main() -> int:
    import asyncio

    async def _run_all():
        await test_context_manager_builds_from_session_queries()
        await test_context_manager_appends_pending_messages()
        await test_context_manager_build_is_stable_and_has_no_summary_side_effects()
        await test_context_manager_new_tool_append_does_not_change_old_tool_content()

    asyncio.run(_run_all())
    print("ContextManager tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
