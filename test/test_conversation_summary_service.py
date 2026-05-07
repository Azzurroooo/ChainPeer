import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ConversationSummaryService


def test_conversation_summary_service_schema() -> None:
    service = ConversationSummaryService()
    messages = [
        {"role": "user", "content": "Please help me refactor the context pipeline."},
        {"role": "assistant", "content": "We already separated model context from persisted history."},
        {"role": "user", "content": "Should we remove chat_history entirely?"},
    ]

    summary = service.summarize(messages)
    rendered = service.render_summary_message(summary)

    expected_keys = {
        "kind",
        "summary_text",
        "current_goal",
        "progress_summary",
        "important_facts",
        "important_decisions",
        "open_questions",
        "covered_turns",
        "source_message_count",
    }
    if set(summary.keys()) != expected_keys:
        raise AssertionError(f"Unexpected summary schema: {summary}")
    if summary["source_message_count"] != 3:
        raise AssertionError(f"Unexpected source message count: {summary}")
    if rendered.get("role") != "assistant":
        raise AssertionError(f"Expected assistant summary message, got: {rendered}")
    if "Conversation summary:" not in rendered.get("content", ""):
        raise AssertionError(f"Expected rendered summary text, got: {rendered}")


def main() -> int:
    test_conversation_summary_service_schema()
    print("Conversation summary service tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
