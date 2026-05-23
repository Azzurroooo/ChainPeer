"""Tests for the framework-level tool telemetry helpers.

These cover the two UX guarantees we promise:
  1. ToolCallStartedEvent.args_preview / ToolResultEvent.summary are
     informative one-liners independent of the LLM's narration.
  2. detect_data_integrity_warning() fires on real data-sourcing failures
     so the runtime can surface a visible banner and prevent fabrication.
"""

from __future__ import annotations

import json

from agent.application.runtime.tool_telemetry import (
    render_args_preview,
    parse_tool_result,
    detect_data_integrity_warning,
)


# ──────────────────────────────────────────────────────────────────────
# render_args_preview
# ──────────────────────────────────────────────────────────────────────


def test_args_preview_bash_shows_command():
    out = render_args_preview("bash", {"command": "ls -la /tmp"})
    assert "$ ls -la /tmp" in out


def test_args_preview_bash_background_marker():
    out = render_args_preview("bash", {"command": "npm start", "run_in_background": True})
    assert "background" in out


def test_args_preview_read_file_shows_path_and_offset():
    out = render_args_preview("read_file", {"file_path": "agent/prompts.py", "offset": 10, "limit": 100})
    assert "agent/prompts.py" in out
    assert "offset=10" in out
    assert "limit=100" in out


def test_args_preview_search_web_shows_query():
    out = render_args_preview("search_web", {"query": "OpenAI base url hboom"})
    assert "OpenAI base url hboom" in out


def test_args_preview_wq_evaluate_shows_expression():
    expr = "ts_rank(close - ts_mean(close, 20), 20)"
    out = render_args_preview("wq_evaluate_alpha", {"expression": expr, "min_sharpe": 1.25})
    assert "ts_rank" in out


def test_args_preview_long_string_is_truncated_with_ellipsis():
    long_cmd = "echo " + "x" * 500
    out = render_args_preview("bash", {"command": long_cmd})
    assert out.endswith("…")
    assert len(out) < 200


def test_args_preview_unknown_tool_falls_back_to_json():
    out = render_args_preview("totally_unknown_tool", {"a": 1, "b": "hi"})
    # Generic fallback should still return SOMETHING informative
    assert "a" in out and "b" in out


def test_args_preview_none_args_returns_empty():
    assert render_args_preview("bash", None) == ""


# ──────────────────────────────────────────────────────────────────────
# parse_tool_result
# ──────────────────────────────────────────────────────────────────────


def test_parse_tool_result_ok_payload_returns_ok_status():
    payload = json.dumps({"ok": True, "tool": "search_web", "data": {"results": [1, 2, 3, 4]}})
    out = parse_tool_result("search_web", payload)
    assert out["status"] == "ok"
    assert "4 results" in out["summary"]


def test_parse_tool_result_error_payload_returns_error_status():
    payload = json.dumps({"ok": False, "tool": "fetch_web_page", "error": "HTTP 503 Service Unavailable", "error_type": "FetchError"})
    out = parse_tool_result("fetch_web_page", payload)
    assert out["status"] == "error"
    assert "503" in out["summary"]


def test_parse_tool_result_plan_create_extracts_snapshot():
    plan = {
        "title": "Mine alpha",
        "goal": "find 3 high-sharpe alphas",
        "version": 1,
        "steps": [
            {"step_id": "s1", "title": "login", "status": "completed"},
            {"step_id": "s2", "title": "snapshot", "status": "in_progress"},
            {"step_id": "s3", "title": "generate", "status": "todo"},
            {"step_id": "s4", "title": "blocked-on-auth", "status": "blocked"},
        ],
    }
    payload = json.dumps({"ok": True, "tool": "plan_create", "data": {"plan": plan}})
    out = parse_tool_result("plan_create", payload)
    assert out["status"] == "ok"
    snap = out.get("plan_snapshot")
    assert snap is not None, "plan tools must surface a plan snapshot"
    assert snap["title"] == "Mine alpha"
    assert snap["total_steps"] == 4
    assert snap["completed_steps"] == 1
    assert snap["in_progress_steps"] == 1
    assert snap["blocked_steps"] == 1
    assert snap["current_focus"] == "snapshot"


def test_parse_tool_result_wq_evaluate_pass_shows_sharpe():
    payload = json.dumps({
        "ok": True,
        "tool": "wq_evaluate_alpha",
        "data": {"passed": True, "metrics": {"sharpe": 1.42}, "stage_failed": None},
    })
    out = parse_tool_result("wq_evaluate_alpha", payload)
    assert "PASSED" in out["summary"]
    assert "1.42" in out["summary"]


def test_parse_tool_result_wq_evaluate_fail_shows_stage():
    payload = json.dumps({
        "ok": True,
        "tool": "wq_evaluate_alpha",
        "data": {
            "passed": False,
            "metrics": {},
            "stage_failed": "stage3_threshold",
            "reason": "sharpe 0.81 below 1.25",
        },
    })
    out = parse_tool_result("wq_evaluate_alpha", payload)
    assert "FAILED" in out["summary"]
    assert "stage3_threshold" in out["summary"]


def test_parse_tool_result_non_json_text_is_passed_through():
    out = parse_tool_result("read_file", "some plain text returned by tool")
    assert out["status"] == "unknown"
    assert "some plain text" in out["summary"]


# ──────────────────────────────────────────────────────────────────────
# detect_data_integrity_warning — THE quant-correctness guarantee
# ──────────────────────────────────────────────────────────────────────


def test_data_integrity_warning_fires_on_fetch_web_page_failure():
    parsed = {"status": "error", "summary": "Error: HTTP 503"}
    warning = detect_data_integrity_warning("fetch_web_page", parsed)
    assert warning is not None
    assert warning["tool_name"] == "fetch_web_page"
    assert "503" in warning["reason"]
    # The action MUST tell the agent not to substitute synthetic data
    assert "synthetic" in warning["suggested_action"].lower() or "not" in warning["suggested_action"].lower()


def test_data_integrity_warning_fires_on_read_file_failure():
    parsed = {"status": "error", "summary": "Error: FileNotFoundError"}
    warning = detect_data_integrity_warning("read_file", parsed)
    assert warning is not None
    assert "fabricate" in warning["suggested_action"].lower()


def test_data_integrity_warning_fires_on_wq_evaluate_alpha_error():
    parsed = {"status": "error", "summary": "Error: WQRateLimitError"}
    warning = detect_data_integrity_warning("wq_evaluate_alpha", parsed)
    assert warning is not None
    # WQ-specific guidance must explicitly forbid mocking metrics
    assert "mock" in warning["suggested_action"].lower() or "fabric" in warning["suggested_action"].lower()


def test_data_integrity_warning_fires_on_bash_failure():
    # bash is in the data-sourcing list because curl/wget data downloads run via it
    parsed = {"status": "error", "summary": "Error: exit code 1"}
    warning = detect_data_integrity_warning("bash", parsed)
    assert warning is not None


def test_data_integrity_warning_does_not_fire_on_success():
    parsed = {"status": "ok", "summary": "10 rows"}
    assert detect_data_integrity_warning("fetch_web_page", parsed) is None


def test_data_integrity_warning_does_not_fire_for_non_data_tools():
    # plan_create is NOT a data-sourcing tool — its failure shouldn't trigger the banner
    parsed = {"status": "error", "summary": "Error: VersionConflict"}
    assert detect_data_integrity_warning("plan_create", parsed) is None
    assert detect_data_integrity_warning("edit_file", parsed) is None
    assert detect_data_integrity_warning("skill_create", parsed) is None


def test_data_integrity_warning_handles_unknown_status_gracefully():
    parsed = {"status": "unknown", "summary": "weird"}
    assert detect_data_integrity_warning("fetch_web_page", parsed) is None
