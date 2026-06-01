import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.application.services.context_estimator import ContextBudget, ContextEstimator
from agent.application.services.context_manager import ContextManager


class MockSession:
    def __init__(self):
        self.messages = []
        self.conversation_summaries = []
        self.context_snapshots = []

    async def get_messages_slice(self):
        return [dict(message) for message in self.messages]

    async def get_tool_records(self, call_ids=None):
        raise AssertionError("append-only context build should not read tool records")

    async def get_tool_summaries(self, call_ids=None):
        raise AssertionError("append-only context build should not read tool summaries")

    async def persist_tool_summary(self, summary):
        raise AssertionError("append-only context build should not persist tool summaries")

    async def get_latest_conversation_summary(self):
        raise AssertionError("append-only context build should not read summaries")

    async def persist_conversation_summary(self, summary):
        self.conversation_summaries.append(summary)

    async def persist_context_snapshot(self, snapshot):
        self.context_snapshots.append(snapshot)


@pytest.mark.asyncio
async def test_context_manager_step_threshold_only_recommends_compact():
    budget = ContextBudget(
        conversation_budget_tokens=10,
        tool_budget_tokens=500,
        hard_limit_tokens=2000,
        compact_threshold_tokens=10,
    )
    manager = ContextManager(estimator=ContextEstimator(budget=budget), hot_message_limit=2, summary_step_threshold=4)
    session = MockSession()
    for index in range(10):
        session.messages.append({"role": "user", "content": f"Message {index} " + ("x" * 40)})

    first = await manager.build_messages_async(session)
    second = await manager.build_messages_async(session)

    assert first.messages == session.messages
    assert second.messages == first.messages
    assert first.decisions["compact_recommended"] is True
    assert first.decisions["rolling_summary_generated"] is False
    assert first.stats["cold_compacted_message_count"] == 0
    assert session.conversation_summaries == []
    assert len(session.context_snapshots) == 2
