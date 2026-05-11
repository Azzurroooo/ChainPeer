import pytest
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dataclasses import asdict, dataclass
from unittest.mock import Mock, patch

from agent.application.services.context_manager import ContextManager, ContextSnapshot
from agent.application.services.context_estimator import ContextEstimator, ContextBudget, ContextEstimate

class MockSession:
    def __init__(self):
        self.messages = []
        self.tool_records = []
        self.tool_summaries = {}
        self.conversation_summaries = []
        self.context_snapshots = []

    async def get_messages_slice(self):
        return self.messages

    async def get_tool_records(self, call_ids=None):
        return self.tool_records

    async def get_tool_summaries(self, call_ids=None):
        return self.tool_summaries

    async def persist_tool_summary(self, summary):
        pass

    async def get_latest_conversation_summary(self):
        if self.conversation_summaries:
            return self.conversation_summaries[-1]
        return None

    async def persist_conversation_summary(self, summary):
        self.conversation_summaries.append(summary)

    async def persist_context_snapshot(self, snapshot):
        self.context_snapshots.append(snapshot)


class MockSummaryService:
    def summarize(self, messages):
        return {
            "source_message_count": len(messages),
            "covered_turns": len(messages) // 2,
            "content": f"Summarized {len(messages)} messages."
        }

    def render_summary_message(self, summary):
        return {
            "role": "user",
            "content": f"PREVIOUS CONVERSATION SUMMARY: {summary['content']}"
        }

@pytest.mark.asyncio
async def test_context_manager_step_compaction():
    # Force the budget to be very small so it always triggers compaction
    budget = ContextBudget(conversation_budget_tokens=10, tool_budget_tokens=500, hard_limit_tokens=2000)
    estimator = ContextEstimator(budget=budget)
    summary_service = MockSummaryService()

    # 2 hot messages, 4 threshold for step summary
    manager = ContextManager(
        estimator=estimator,
        summary_service=summary_service,
        hot_message_limit=2,
        summary_step_threshold=4
    )

    session = MockSession()

    # Add 10 messages (all will be over soft limit)
    # 8 will be cold, 2 will be hot
    for i in range(10):
        session.messages.append({"role": "user", "content": f"Message {i}"})

    # First build: should generate summary for 8 cold messages
    result = await manager.build_messages_async(session)
    assert result.decisions["rolling_summary_generated"] == True
    assert result.stats["cold_compacted_message_count"] == 8
    assert len(session.conversation_summaries) == 1
    assert session.conversation_summaries[0]["source_message_count"] == 8

    # Now add 2 more messages (total 12)
    # 10 will be cold, 2 will be hot.
    # The new cold messages count is 10, previous was 8.
    # Difference is 2 < 4 (threshold). It should REUSE the summary.
    session.messages.append({"role": "user", "content": "Message 10"})
    session.messages.append({"role": "user", "content": "Message 11"})

    result2 = await manager.build_messages_async(session)
    # Should NOT generate a new summary
    assert result2.decisions["rolling_summary_generated"] == False
    # Covered count is 8, so it skipped 8 messages, kept 2 old cold messages + 2 hot messages + 1 summary = 5 total
    assert len(result2.messages) == 5
    assert result2.messages[0]["content"].startswith("PREVIOUS CONVERSATION")
    assert result2.messages[1]["content"] == "Message 8" # The unsummarized cold message
    assert result2.messages[2]["content"] == "Message 9" # The unsummarized cold message
    assert result2.messages[3]["content"] == "Message 10" # Hot message
    assert result2.messages[4]["content"] == "Message 11" # Hot message

    # Now add 3 more messages (total 15)
    # 13 will be cold, 2 will be hot.
    # New cold count is 13, previous was 8.
    # Difference is 5 > 4 (threshold). It should GENERATE a NEW summary.
    session.messages.append({"role": "user", "content": "Message 12"})
    session.messages.append({"role": "user", "content": "Message 13"})
    session.messages.append({"role": "user", "content": "Message 14"})

    result3 = await manager.build_messages_async(session)
    assert result3.decisions["rolling_summary_generated"] == True
    assert len(session.conversation_summaries) == 2
    assert session.conversation_summaries[-1]["source_message_count"] == 13

    # The new result should have 1 summary + 2 hot messages = 3 messages
    assert len(result3.messages) == 3
    assert result3.messages[0]["content"].startswith("PREVIOUS CONVERSATION")
    assert result3.messages[1]["content"] == "Message 13" # Hot message
    assert result3.messages[2]["content"] == "Message 14" # Hot message
