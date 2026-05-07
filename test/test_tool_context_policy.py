import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ToolContextPolicy


def test_tool_temperature_classification() -> None:
    policy = ToolContextPolicy(hot_batch_limit=1, warm_batch_limit=4)
    temperatures = policy.classify_temperatures([["a", "b"], ["c"], ["d", "e"], ["f"], ["g"], ["h"]])
    expected = {"a": "cold", "b": "cold", "c": "warm", "d": "warm", "e": "warm", "f": "warm", "g": "warm", "h": "hot"}
    if temperatures != expected:
        raise AssertionError(f"Unexpected temperature map: {temperatures}")


def test_tool_rendering_uses_more_compact_payload_for_colder_tools() -> None:
    policy = ToolContextPolicy()
    tool_record = {
        "id": "call_1",
        "name": "fetch_web_page",
        "result": {"ok": True, "tool": "fetch_web_page", "data": "x" * 4000},
    }
    summary = policy.build_tool_summary_record(tool_record)
    hot_content = policy.render_tool_message(tool_record, None, "hot")
    warm_content = policy.render_tool_message(tool_record, summary, "warm")
    cold_content = policy.render_tool_message(tool_record, summary, "cold")

    if len(hot_content) <= len(warm_content):
        raise AssertionError("Expected hot tool rendering to preserve more content than warm rendering.")
    if len(warm_content) <= len(cold_content):
        raise AssertionError("Expected warm tool rendering to preserve more context than cold rendering.")
    if '"data_excerpt"' not in warm_content:
        raise AssertionError(f"Expected warm payload to include data excerpt, got: {warm_content}")
    if '"data_excerpt"' in cold_content or '"data_summary"' in cold_content:
        raise AssertionError(f"Expected cold payload to omit data details, got: {cold_content}")


def test_tool_rendering_applies_dynamic_char_budget() -> None:
    policy = ToolContextPolicy()
    tool_record = {
        "id": "call_1",
        "name": "fetch_web_page",
        "result": {"ok": True, "tool": "fetch_web_page", "data": "x" * 8000},
    }
    content = policy.render_tool_message(tool_record, None, "hot", available_chars=120)
    if len(content) > 120:
        raise AssertionError(f"Expected content within dynamic budget, got length={len(content)}")
    if "Output truncated due to context limits" not in content:
        raise AssertionError(f"Expected truncation hint in payload, got: {content}")


def test_tool_rendering_returns_empty_when_budget_exhausted() -> None:
    policy = ToolContextPolicy()
    tool_record = {
        "id": "call_1",
        "name": "fetch_web_page",
        "result": {"ok": True, "tool": "fetch_web_page", "data": "x" * 1000},
    }
    content = policy.render_tool_message(tool_record, None, "hot", available_chars=0)
    if content != "":
        raise AssertionError(f"Expected empty content for exhausted budget, got: {content!r}")


def main() -> int:
    test_tool_temperature_classification()
    test_tool_rendering_uses_more_compact_payload_for_colder_tools()
    test_tool_rendering_applies_dynamic_char_budget()
    test_tool_rendering_returns_empty_when_budget_exhausted()
    print("Tool context policy tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
