"""Framework-level telemetry helpers for tool calls.

Centralizes the rendering of human-readable previews/summaries for tool
arguments and results, so the CLI can show a live progress panel without
trusting the LLM to narrate its own actions.

Three concerns live here:

1. ``render_args_preview(tool_name, args)`` — one-line "what is about to run".
2. ``parse_tool_result(tool_name, payload_str)`` — extract ok/error + summary
   + (for plan tools) a structured PlanSnapshot fragment.
3. ``detect_data_integrity_warning(tool_name, parsed)`` — heuristic to flag
   data-source failures that the model MUST report instead of fabricate.

Everything is best-effort and never raises — telemetry is for UX, not logic.
"""

from __future__ import annotations

import json
from typing import Any

# Hard cap so the CLI panel never blows up; longer args get a "…" suffix.
_PREVIEW_MAX = 160


def _shorten(text: str, limit: int = _PREVIEW_MAX) -> str:
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def render_args_preview(tool_name: str, args: dict[str, Any] | None) -> str:
    """Return a short, human-readable description of what the tool will do."""
    if not isinstance(args, dict):
        return ""

    try:
        # bash: show the command directly
        if tool_name == "bash":
            cmd = args.get("command", "")
            bg = args.get("run_in_background")
            tail = " (background)" if bg else ""
            return _shorten(f"$ {cmd}{tail}")
        if tool_name == "bash_output":
            bid = args.get("bg_id", "")
            return _shorten(f"bg_id={bid}{' (kill)' if args.get('kill') else ''}")
        if tool_name == "kill_shell":
            return "reset shell session"

        # file ops
        if tool_name == "read_file":
            offset = args.get("offset")
            limit = args.get("limit")
            extra = []
            if offset:
                extra.append(f"offset={offset}")
            if limit:
                extra.append(f"limit={limit}")
            suffix = f" [{', '.join(extra)}]" if extra else ""
            return _shorten(f"{args.get('file_path', '?')}{suffix}")
        if tool_name == "read_pdf":
            sp, ep = args.get("start_page"), args.get("end_page")
            range_part = f" [{sp or 1}-{ep or 'end'}]"
            return _shorten(f"{args.get('file_path', '?')}{range_part}")
        if tool_name == "write_file":
            content = args.get("content", "")
            size = len(content) if isinstance(content, str) else 0
            return _shorten(f"{args.get('file_path', '?')} ({size} chars)")
        if tool_name == "edit_file":
            old = args.get("old_str", "")
            old_preview = _shorten(old, 60)
            return _shorten(f"{args.get('file_path', '?')} replace «{old_preview}»")
        if tool_name == "list_files":
            directory = args.get("directory", ".")
            pattern = args.get("pattern", "")
            extra = f" [{pattern}]" if pattern else ""
            return _shorten(f"{directory}{extra}")
        if tool_name == "grep":
            pattern = args.get("pattern", "")
            path = args.get("path", ".")
            glob = args.get("glob_pattern", "")
            extra = f" in {glob}" if glob else ""
            return _shorten(f"/{pattern}/ in {path}{extra}")

        # web
        if tool_name == "search_web":
            return _shorten(f'query="{args.get("query", "")}"')
        if tool_name == "fetch_web_page":
            return _shorten(args.get("url", ""))

        # plan
        if tool_name == "plan_create":
            title = args.get("title", "")
            n_steps = len(args.get("steps") or [])
            return _shorten(f'"{title}" ({n_steps} steps)')
        if tool_name in {
            "plan_get",
            "plan_next",
        }:
            mode = args.get("mode") or ""
            return _shorten(mode) if mode else ""
        if tool_name == "plan_update_step":
            return _shorten(f"step={args.get('step_id', '?')} patch={args.get('patch', {})}")
        if tool_name == "plan_close":
            return _shorten(args.get("summary", ""))

        # skill
        if tool_name == "skill_create":
            return _shorten(f"{args.get('scope', 'project')}/{args.get('name', '?')}")

        # WorldQuant Brain — show the most informative field per tool
        if tool_name == "wq_login":
            email = args.get("email", "")
            return _shorten(email) if email else "(env credentials)"
        if tool_name == "wq_evaluate_alpha" or tool_name == "wq_simulate_alpha":
            return _shorten(args.get("expression", ""))
        if tool_name == "wq_build_generation_prompt":
            return _shorten(f"direction={args.get('direction_key', '?')} n={args.get('n', 5)}")
        if tool_name == "wq_mutate_alpha":
            return _shorten(args.get("seed_expression", ""))
        if tool_name == "wq_crossover_alpha":
            a = _shorten(args.get("expression_a", ""), 50)
            b = _shorten(args.get("expression_b", ""), 50)
            return _shorten(f"{a} × {b}")
        if tool_name == "wq_distill_insight":
            return _shorten(args.get("insight", ""))
        if tool_name == "wq_submit_alpha":
            return _shorten(args.get("alpha_id", ""))

        # Generic fallback: JSON-serialise top-level keys
        try:
            return _shorten(json.dumps(args, ensure_ascii=False, default=str))
        except Exception:
            return _shorten(str(args))
    except Exception:
        return ""


def parse_tool_result(tool_name: str, payload_str: str) -> dict[str, Any]:
    """Best-effort parse of the standardized tool_ok/tool_error JSON payload.

    Returns a dict with keys: ``status`` (ok/error/unknown), ``summary`` (str),
    and optionally ``plan_snapshot`` (dict) when the tool is a plan_* tool.
    Never raises.
    """
    result: dict[str, Any] = {"status": "unknown", "summary": "", "data": None}
    if not isinstance(payload_str, str) or not payload_str:
        return result
    try:
        obj = json.loads(payload_str)
    except Exception:
        # Some tools return plain text on success
        result["summary"] = _shorten(payload_str)
        return result

    if not isinstance(obj, dict):
        result["summary"] = _shorten(payload_str)
        return result

    ok = obj.get("ok")
    if ok is True:
        result["status"] = "ok"
        data = obj.get("data")
        result["data"] = data
        result["summary"] = _summarize_ok_payload(tool_name, data)
        plan_snap = _extract_plan_snapshot(tool_name, data)
        if plan_snap:
            result["plan_snapshot"] = plan_snap
    elif ok is False:
        result["status"] = "error"
        err = obj.get("error") or obj.get("error_type") or "unknown error"
        result["summary"] = _shorten(f"Error: {err}")
    else:
        result["summary"] = _shorten(payload_str)
    return result


def _summarize_ok_payload(tool_name: str, data: Any) -> str:
    """Compact one-line summary of an `ok` data payload, per-tool aware."""
    if data is None:
        return "ok"
    try:
        if tool_name in {"read_file", "read_pdf"}:
            if isinstance(data, dict):
                content = data.get("content") or data.get("text") or ""
                lines = content.count("\n") + (1 if content else 0)
                return f"{lines} lines, {len(content)} chars"
            if isinstance(data, str):
                lines = data.count("\n") + (1 if data else 0)
                return f"{lines} lines, {len(data)} chars"
        if tool_name == "list_files":
            if isinstance(data, dict):
                files = data.get("files") or data.get("entries") or []
                return f"{len(files)} entries"
        if tool_name == "grep":
            if isinstance(data, dict):
                matches = data.get("matches") or data.get("results") or []
                return f"{len(matches)} matches"
        if tool_name == "bash":
            if isinstance(data, dict):
                stdout = data.get("stdout", "")
                stderr = data.get("stderr", "")
                exit_code = data.get("exit_code")
                stdout_lines = stdout.count("\n") + (1 if stdout else 0)
                tag = f"exit={exit_code}" if exit_code is not None else "ok"
                err_part = f", {stderr.count(chr(10)) + 1} stderr lines" if stderr else ""
                return f"{tag}, {stdout_lines} stdout lines{err_part}"
        if tool_name == "search_web":
            if isinstance(data, dict):
                items = data.get("results") or []
                return f"{len(items)} results"
        if tool_name == "fetch_web_page":
            if isinstance(data, dict):
                text = data.get("content") or data.get("text") or ""
                return f"{len(text)} chars"
        if tool_name == "wq_evaluate_alpha":
            if isinstance(data, dict):
                passed = data.get("passed")
                metrics = data.get("metrics") or {}
                sharpe = metrics.get("sharpe")
                stage = data.get("stage_failed")
                if passed:
                    return f"PASSED sharpe={sharpe}"
                return f"FAILED at {stage or '?'} ({data.get('reason', '')[:80]})"
        if tool_name == "wq_simulate_alpha":
            if isinstance(data, dict):
                sharpe = (data.get("metrics") or {}).get("sharpe") if isinstance(data.get("metrics"), dict) else None
                return f"sharpe={sharpe}" if sharpe is not None else "ok"
        if tool_name == "wq_list_library" or tool_name == "wq_list_my_alphas":
            if isinstance(data, dict):
                n = data.get("count")
                if n is None and isinstance(data.get("alphas"), list):
                    n = len(data["alphas"])
                return f"{n} alphas" if n is not None else "ok"
        if tool_name == "wq_memory_snapshot":
            if isinstance(data, dict):
                p_succ = data.get("p_succ") or []
                p_fail = data.get("p_fail") or []
                ins = data.get("insights") or []
                return f"P_succ={len(p_succ)} P_fail={len(p_fail)} I={len(ins)}"
        if tool_name == "wq_mutate_alpha":
            if isinstance(data, dict):
                return f"{len(data.get('variants') or [])} variants"
        # Generic fallback
        if isinstance(data, (list, tuple)):
            return f"{len(data)} items"
        if isinstance(data, dict):
            return f"{len(data)} keys"
        return _shorten(str(data))
    except Exception:
        return "ok"


def _extract_plan_snapshot(tool_name: str, data: Any) -> dict[str, Any] | None:
    """If this is a plan_* tool result, extract a snapshot dict for the CLI panel."""
    if not tool_name.startswith("plan_"):
        return None
    if not isinstance(data, dict):
        return None

    # Different plan tools return the plan in different shapes; try a few keys.
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    if plan is None and "steps" in data and "title" in data:
        plan = data
    if plan is None:
        return None

    steps = plan.get("steps") or []
    if not isinstance(steps, list):
        steps = []

    counts = {"completed": 0, "in_progress": 0, "blocked": 0, "todo": 0, "cancelled": 0}
    current_focus = ""
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = str(step.get("status") or "todo").lower()
        if status in counts:
            counts[status] += 1
        if status == "in_progress" and not current_focus:
            current_focus = str(step.get("title") or step.get("step_id") or "")

    return {
        "title": str(plan.get("title") or ""),
        "goal": str(plan.get("goal") or ""),
        "total_steps": len(steps),
        "completed_steps": counts["completed"],
        "in_progress_steps": counts["in_progress"],
        "blocked_steps": counts["blocked"],
        "current_focus": current_focus,
        "version": int(plan.get("version") or 0),
    }


# ──────────────────────────────────────────────────────────────────────
# Data integrity heuristic
# ──────────────────────────────────────────────────────────────────────

# Tools that fetch/produce REAL external data. When these fail, the agent
# MUST report the failure to the user and propose remediation — it is
# strictly forbidden to substitute fabricated, randomly-generated, or
# placeholder data, especially in quant workflows where accuracy is
# correctness.
_DATA_SOURCING_TOOLS = frozenset(
    {
        "fetch_web_page",
        "search_web",
        "read_file",
        "read_pdf",
        "bash",  # data downloads commonly happen via curl/wget
        # WorldQuant Brain — the entire alpha-mining loop depends on real Brain data
        "wq_login",
        "wq_list_data_fields",
        "wq_list_operators",
        "wq_simulate_alpha",
        "wq_evaluate_alpha",
        "wq_list_library",
        "wq_list_my_alphas",
        "wq_submit_alpha",
        "wq_memory_snapshot",
    }
)


def detect_data_integrity_warning(
    tool_name: str, parsed_result: dict[str, Any]
) -> dict[str, str] | None:
    """If a data-sourcing tool failed, return a warning dict for the CLI/audit log.

    Returns None when no warning should fire. Pure heuristic — never raises.
    """
    if tool_name not in _DATA_SOURCING_TOOLS:
        return None
    if parsed_result.get("status") != "error":
        return None

    reason = str(parsed_result.get("summary") or "data source failed").lstrip("Error: ").strip()
    suggested_action = _suggested_remediation(tool_name)
    return {
        "tool_name": tool_name,
        "reason": _shorten(reason, 200),
        "suggested_action": suggested_action,
    }


def _suggested_remediation(tool_name: str) -> str:
    if tool_name in {"fetch_web_page", "search_web"}:
        return (
            "Report the data-source failure to the user; offer to retry, try a "
            "different URL/query, or check network. Do NOT substitute synthetic data."
        )
    if tool_name in {"read_file", "read_pdf"}:
        return (
            "Tell the user the file is unreadable (missing / permission / corrupt) and "
            "ask for the correct path. Do NOT fabricate file contents."
        )
    if tool_name == "bash":
        return (
            "Show the user the command, exit code, and stderr; ask whether to retry or "
            "skip. Do NOT pretend the command succeeded or invent its output."
        )
    if tool_name.startswith("wq_"):
        return (
            "Tell the user the WorldQuant Brain call failed (auth/quota/network) and "
            "stop the Ralph Loop. Do NOT proceed by mocking simulation metrics — "
            "fabricated alpha metrics are worse than no metrics."
        )
    return "Report the failure to the user; do not fabricate the missing data."
