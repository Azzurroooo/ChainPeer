import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import CompactionService


class FakeSession:
    def __init__(self):
        self.records = []

    async def load_messages(self):
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "goal"},
            {"role": "assistant", "content": "progress"},
        ]

    async def get_tool_records(self, *args, **kwargs):
        return []

    async def get_latest_compaction(self):
        return None

    async def persist_compaction(self, record):
        self.records.append(dict(record))
        return dict(record)


@pytest.mark.asyncio
async def test_compaction_service_falls_back_when_llm_compact_fails() -> None:
    class FailingClient:
        async def create(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    session = FakeSession()
    record = await CompactionService().compact_async(
        session=session,
        context_messages=await session.load_messages(),
        chat_client=FailingClient(),
        reason="auto",
        phase="mid_turn",
        context_stats={"context_window_tokens": 1000, "effective_context_window_tokens": 950},
    )

    assert record["strategy"] == "deterministic_fallback"
    assert record["reason"] == "auto"
    assert record["phase"] == "mid_turn"
    assert record["policy_version"] == "compact_boundary_v2"
    assert record["fallback_error"]["type"] == "RuntimeError"
    assert record["handoff_message"]["content"].startswith("Context compacted.")
    assert session.records[-1]["source"]["message_start_index"] == 0


@pytest.mark.asyncio
async def test_compaction_service_keeps_llm_handoff_when_usage_persist_fails() -> None:
    class UsageFailingSession(FakeSession):
        async def persist_sampling_usage(self, usage):
            raise RuntimeError("usage store unavailable")

    class SuccessfulClient:
        async def create(self, *args, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="LLM compact handoff"))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            )

    session = UsageFailingSession()
    record = await CompactionService().compact_async(
        session=session,
        context_messages=await session.load_messages(),
        chat_client=SuccessfulClient(),
        reason="manual",
        phase="manual",
        context_stats={"context_window_tokens": 1000, "effective_context_window_tokens": 900},
    )

    assert record["strategy"] == "llm_inline"
    assert record["handoff_message"]["content"] == "LLM compact handoff"
    assert record["usage"]["input_tokens"] == 100
    assert record["usage_persist_error"]["type"] == "RuntimeError"
    assert "fallback_error" not in record


def main() -> int:
    import asyncio

    asyncio.run(test_compaction_service_falls_back_when_llm_compact_fails())
    asyncio.run(test_compaction_service_keeps_llm_handoff_when_usage_persist_fails())
    print("CompactionService tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
