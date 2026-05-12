"""Plan management tool with DAG dependencies and optimistic locking."""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.domain import tool_error, tool_ok

PLAN_SCHEMA_VERSION = "1.0"
PLAN_STATUS = {"active", "completed", "canceled"}
STEP_STATUS = {"pending", "in_progress", "blocked", "completed", "canceled"}
STEP_MUTABLE_FIELDS = {"title", "description", "priority", "owner", "acceptance", "note", "blocked_reason"}
STEP_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "blocked", "canceled"},
    "in_progress": {"completed", "blocked", "pending", "canceled"},
    "blocked": {"pending", "in_progress", "canceled"},
    "completed": set(),
    "canceled": set(),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _resolve_session_base() -> tuple[Path, str]:
    env_root = os.getenv("AGENT_SESSION_ROOT")
    env_id = os.getenv("AGENT_SESSION_ID")
    if env_root and env_id:
        base = Path(env_root) / env_id
        if base.is_dir():
            return base, env_id
    raise FileNotFoundError(
        "No active session context found. Ensure session is initialized before using plan tools "
        "(missing AGENT_SESSION_ROOT / AGENT_SESSION_ID)."
    )


def _plan_paths() -> tuple[Path, Path, str]:
    base, sid = _resolve_session_base()
    return base / "plan.json", base / "plan_events.jsonl", sid


def _load_plan() -> tuple[dict[str, Any], Path, Path]:
    plan_file, events_file, session_id = _plan_paths()
    if not plan_file.exists():
        raise FileNotFoundError(f"No plan found in current session: {session_id}")
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted plan file: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError("Corrupted plan file: expected object.")
    return plan, plan_file, events_file


def _append_event(events_file: Path, event: dict[str, Any]) -> None:
    line = json.dumps(event, ensure_ascii=False)
    with events_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _step_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("step_id"), str):
            out[step["step_id"]] = step
    return out


def _assert_expected_version(plan: dict[str, Any], expected_version: int) -> None:
    current = int(plan.get("version", 0))
    if current != expected_version:
        raise RuntimeError(f"VersionConflict: expected {expected_version}, current {current}")


def _validate_plan_status(status: str) -> None:
    if status not in PLAN_STATUS:
        raise ValueError(f"Invalid plan status: {status}")


def _validate_step_status(status: str) -> None:
    if status not in STEP_STATUS:
        raise ValueError(f"Invalid step status: {status}")


def _all_deps_completed(step: dict[str, Any], step_by_id: dict[str, dict[str, Any]]) -> bool:
    deps = step.get("depends_on") or []
    if not isinstance(deps, list):
        return False
    for dep_id in deps:
        dep = step_by_id.get(dep_id)
        if not dep or dep.get("status") != "completed":
            return False
    return True


def _validate_graph_no_cycle(step_by_id: dict[str, dict[str, Any]]) -> None:
    edges: dict[str, list[str]] = {}
    for sid, step in step_by_id.items():
        deps = step.get("depends_on") or []
        if not isinstance(deps, list):
            raise ValueError(f"Step {sid} depends_on must be a list.")
        for dep_id in deps:
            if dep_id not in step_by_id:
                raise ValueError(f"Step {sid} depends on unknown step: {dep_id}")
            if dep_id == sid:
                raise ValueError(f"Step {sid} cannot depend on itself.")
        edges[sid] = [d for d in deps if isinstance(d, str)]

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise ValueError("CycleDetected: dependency cycle found.")
        visiting.add(node)
        for nxt in edges.get(node, []):
            dfs(nxt)
        visiting.remove(node)
        visited.add(node)

    for key in edges:
        dfs(key)


def _bump_version(plan: dict[str, Any]) -> tuple[int, int]:
    old = int(plan.get("version", 0))
    new = old + 1
    plan["version"] = new
    plan["updated_at"] = _now_iso()
    return old, new


def _persist_plan_update(
    *,
    plan: dict[str, Any],
    plan_file: Path,
    events_file: Path,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    old_version, new_version = _bump_version(plan)
    event = {
        "event_id": uuid.uuid4().hex,
        "ts": _now_iso(),
        "actor": "agent",
        "plan_id": plan.get("plan_id"),
        "type": event_type,
        "payload": payload,
        "from_version": old_version,
        "to_version": new_version,
    }
    _append_event(events_file, event)
    _write_json_atomic(plan_file, plan)


def _normalized_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise ValueError(f"Step at index {index} must be object.")
    title = str(step.get("title", "")).strip()
    if not title:
        raise ValueError(f"Step at index {index} missing title.")
    step_id = str(step.get("step_id") or f"step_{index + 1}")
    depends_on = step.get("depends_on") or []
    if not isinstance(depends_on, list):
        raise ValueError(f"Step {step_id} depends_on must be a list.")
    status = str(step.get("status") or "pending")
    _validate_step_status(status)
    now = _now_iso()
    return {
        "step_id": step_id,
        "title": title,
        "description": str(step.get("description") or ""),
        "status": status,
        "depends_on": [str(x) for x in depends_on],
        "priority": int(step.get("priority", 0)),
        "owner": str(step.get("owner") or ""),
        "acceptance": str(step.get("acceptance") or ""),
        "note": str(step.get("note") or ""),
        "blocked_reason": str(step.get("blocked_reason") or ""),
        "created_at": now,
        "updated_at": now,
        "order": index,
    }


def _depth(sid: str, steps: dict[str, dict[str, Any]], memo: dict[str, int]) -> int:
    if sid in memo:
        return memo[sid]
    deps = steps[sid].get("depends_on") or []
    if not deps:
        memo[sid] = 0
        return 0
    value = 1 + max(_depth(d, steps, memo) for d in deps if d in steps)
    memo[sid] = value
    return value


def plan_create(title: str, goal: str, steps: list[dict[str, Any]], expected_version: int | None = None) -> str:
    try:
        plan_file, events_file, session_id = _plan_paths()
        if plan_file.exists():
            current = json.loads(plan_file.read_text(encoding="utf-8"))
            if expected_version is None:
                return tool_error("plan_create", "Active plan already exists.", "ValidationError")
            _assert_expected_version(current, expected_version)

        normalized = [_normalized_step(item, i) for i, item in enumerate(steps)]
        if not normalized:
            return tool_error("plan_create", "steps cannot be empty.", "ValidationError")
        step_by_id = {item["step_id"]: item for item in normalized}
        if len(step_by_id) != len(normalized):
            return tool_error("plan_create", "Duplicate step_id found.", "ValidationError")
        _validate_graph_no_cycle(step_by_id)
        for step in normalized:
            if step["status"] in {"in_progress", "completed"} and not _all_deps_completed(step, step_by_id):
                return tool_error("plan_create", f"Step {step['step_id']} violates dependency precondition.", "DependencyViolation")

        now = _now_iso()
        plan = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": uuid.uuid4().hex[:12],
            "session_id": session_id,
            "title": title.strip(),
            "goal": goal.strip(),
            "status": "active",
            "summary": "",
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "steps": normalized,
        }
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(plan_file, plan)
        _append_event(
            events_file,
            {
                "event_id": uuid.uuid4().hex,
                "ts": now,
                "actor": "agent",
                "plan_id": plan["plan_id"],
                "type": "plan_created",
                "payload": {"title": plan["title"], "goal": plan["goal"], "steps": len(plan["steps"])},
                "from_version": 0,
                "to_version": 1,
            },
        )
        return tool_ok("plan_create", plan, meta={"plan_id": plan["plan_id"], "version": plan["version"]})
    except FileNotFoundError as exc:
        return tool_error("plan_create", str(exc), "NotFound")
    except RuntimeError as exc:
        return tool_error("plan_create", str(exc), "VersionConflict")
    except ValueError as exc:
        code = "CycleDetected" if "CycleDetected" in str(exc) else "ValidationError"
        return tool_error("plan_create", str(exc), code)
    except Exception as exc:
        return tool_error("plan_create", str(exc), type(exc).__name__)


def plan_get(plan_id: str | None = None) -> str:
    try:
        plan, _, _ = _load_plan()
        if plan_id and plan.get("plan_id") != plan_id:
            return tool_error("plan_get", f"Plan not found: {plan_id}", "NotFound")
        return tool_ok("plan_get", plan, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version")})
    except FileNotFoundError as exc:
        return tool_error("plan_get", str(exc), "NotFound")
    except Exception as exc:
        return tool_error("plan_get", str(exc), type(exc).__name__)


def plan_update_step(step_id: str, patch: dict[str, Any], expected_version: int) -> str:
    try:
        plan, plan_file, events_file = _load_plan()
        _validate_plan_status(str(plan.get("status")))
        if plan.get("status") != "active":
            return tool_error("plan_update_step", "Plan is not active.", "ValidationError")
        _assert_expected_version(plan, expected_version)
        if not isinstance(patch, dict):
            return tool_error("plan_update_step", "patch must be object.", "ValidationError")

        step_by_id = _step_map(plan)
        step = step_by_id.get(step_id)
        if not step:
            return tool_error("plan_update_step", f"Step not found: {step_id}", "NotFound")

        before = copy.deepcopy(step)
        requested_status = patch.get("status")
        if requested_status is not None:
            requested_status = str(requested_status)
            _validate_step_status(requested_status)
            current_status = str(step.get("status"))
            if requested_status != current_status and requested_status not in STEP_TRANSITIONS.get(current_status, set()):
                return tool_error("plan_update_step", f"Illegal transition: {current_status} -> {requested_status}", "InvalidTransition")
            if requested_status in {"in_progress", "completed"} and not _all_deps_completed(step, step_by_id):
                return tool_error("plan_update_step", f"Dependencies not completed for step: {step_id}", "DependencyViolation")
            if requested_status == "blocked":
                reason = str(patch.get("blocked_reason") or step.get("blocked_reason") or "").strip()
                if not reason:
                    return tool_error("plan_update_step", "blocked status requires blocked_reason.", "ValidationError")
            step["status"] = requested_status

        for key, value in patch.items():
            if key == "status":
                continue
            if key not in STEP_MUTABLE_FIELDS:
                return tool_error("plan_update_step", f"Unsupported patch field: {key}", "ValidationError")
            if key == "priority":
                step[key] = int(value)
            else:
                step[key] = str(value or "")

        if step.get("status") != "blocked":
            step["blocked_reason"] = ""
        step["updated_at"] = _now_iso()
        _persist_plan_update(
            plan=plan,
            plan_file=plan_file,
            events_file=events_file,
            event_type="step_updated",
            payload={"step_id": step_id, "before": before, "after": step},
        )
        return tool_ok("plan_update_step", step, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version"), "step_id": step_id})
    except FileNotFoundError as exc:
        return tool_error("plan_update_step", str(exc), "NotFound")
    except RuntimeError as exc:
        return tool_error("plan_update_step", str(exc), "VersionConflict")
    except ValueError as exc:
        return tool_error("plan_update_step", str(exc), "ValidationError")
    except Exception as exc:
        return tool_error("plan_update_step", str(exc), type(exc).__name__)


def plan_link_dependency(step_id: str, depends_on: list[str], expected_version: int) -> str:
    try:
        plan, plan_file, events_file = _load_plan()
        _assert_expected_version(plan, expected_version)
        if not isinstance(depends_on, list):
            return tool_error("plan_link_dependency", "depends_on must be array.", "ValidationError")
        step_by_id = _step_map(plan)
        step = step_by_id.get(step_id)
        if not step:
            return tool_error("plan_link_dependency", f"Step not found: {step_id}", "NotFound")
        updated = [str(x) for x in depends_on]
        step["depends_on"] = list(dict.fromkeys(updated))
        _validate_graph_no_cycle(step_by_id)
        step["updated_at"] = _now_iso()
        _persist_plan_update(
            plan=plan,
            plan_file=plan_file,
            events_file=events_file,
            event_type="step_dependency_updated",
            payload={"step_id": step_id, "depends_on": step["depends_on"]},
        )
        return tool_ok("plan_link_dependency", step, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version"), "step_id": step_id})
    except FileNotFoundError as exc:
        return tool_error("plan_link_dependency", str(exc), "NotFound")
    except RuntimeError as exc:
        return tool_error("plan_link_dependency", str(exc), "VersionConflict")
    except ValueError as exc:
        code = "CycleDetected" if "CycleDetected" in str(exc) else "ValidationError"
        return tool_error("plan_link_dependency", str(exc), code)
    except Exception as exc:
        return tool_error("plan_link_dependency", str(exc), type(exc).__name__)


def plan_reorder(step_orders: list[str], expected_version: int) -> str:
    try:
        plan, plan_file, events_file = _load_plan()
        _assert_expected_version(plan, expected_version)
        if not isinstance(step_orders, list):
            return tool_error("plan_reorder", "step_orders must be array.", "ValidationError")
        step_by_id = _step_map(plan)
        if set(step_orders) != set(step_by_id.keys()):
            return tool_error("plan_reorder", "step_orders must include each step exactly once.", "ValidationError")
        for idx, sid in enumerate(step_orders):
            step_by_id[sid]["order"] = idx
            step_by_id[sid]["updated_at"] = _now_iso()
        _persist_plan_update(
            plan=plan,
            plan_file=plan_file,
            events_file=events_file,
            event_type="plan_reordered",
            payload={"step_orders": step_orders},
        )
        ordered = sorted(step_by_id.values(), key=lambda x: int(x.get("order", 0)))
        return tool_ok("plan_reorder", ordered, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version")})
    except FileNotFoundError as exc:
        return tool_error("plan_reorder", str(exc), "NotFound")
    except RuntimeError as exc:
        return tool_error("plan_reorder", str(exc), "VersionConflict")
    except Exception as exc:
        return tool_error("plan_reorder", str(exc), type(exc).__name__)


def plan_next(mode: str, expected_version: int | None = None) -> str:
    try:
        plan, _, _ = _load_plan()
        if expected_version is not None:
            _assert_expected_version(plan, expected_version)
        if mode not in {"ready", "focus", "blocked_report"}:
            return tool_error("plan_next", "mode must be one of: ready, focus, blocked_report.", "ValidationError")
        step_by_id = _step_map(plan)
        ordered = sorted(step_by_id.values(), key=lambda x: int(x.get("order", 0)))

        ready = [s for s in ordered if s.get("status") == "pending" and _all_deps_completed(s, step_by_id)]
        if mode == "ready":
            return tool_ok("plan_next", ready, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version"), "count": len(ready)})

        if mode == "blocked_report":
            blocked: list[dict[str, Any]] = []
            for step in ordered:
                if step.get("status") == "blocked":
                    blocked.append({"step_id": step["step_id"], "reason": step.get("blocked_reason") or "blocked"})
                    continue
                if step.get("status") == "pending":
                    deps = step.get("depends_on") or []
                    missing = [d for d in deps if d in step_by_id and step_by_id[d].get("status") != "completed"]
                    if missing:
                        blocked.append({"step_id": step["step_id"], "reason": "waiting_dependencies", "blocked_by": missing})
            return tool_ok("plan_next", blocked, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version"), "count": len(blocked)})

        if not ready:
            return tool_ok("plan_next", None, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version"), "reason": "no_ready_steps"})
        memo: dict[str, int] = {}
        ready_sorted = sorted(
            ready,
            key=lambda x: (
                -int(x.get("priority", 0)),
                _depth(x["step_id"], step_by_id, memo),
                int(x.get("order", 0)),
            ),
        )
        return tool_ok("plan_next", ready_sorted[0], meta={"plan_id": plan.get("plan_id"), "version": plan.get("version"), "mode": "focus"})
    except FileNotFoundError as exc:
        return tool_error("plan_next", str(exc), "NotFound")
    except RuntimeError as exc:
        return tool_error("plan_next", str(exc), "VersionConflict")
    except Exception as exc:
        return tool_error("plan_next", str(exc), type(exc).__name__)


def plan_close(summary: str, expected_version: int) -> str:
    try:
        plan, plan_file, events_file = _load_plan()
        _assert_expected_version(plan, expected_version)
        step_by_id = _step_map(plan)
        unfinished = [sid for sid, step in step_by_id.items() if step.get("status") not in {"completed", "canceled"}]
        if unfinished:
            return tool_error("plan_close", f"Cannot close plan with unfinished steps: {unfinished}", "DependencyViolation")
        plan["status"] = "completed"
        plan["summary"] = summary.strip()
        _persist_plan_update(
            plan=plan,
            plan_file=plan_file,
            events_file=events_file,
            event_type="plan_closed",
            payload={"summary": plan["summary"]},
        )
        return tool_ok("plan_close", plan, meta={"plan_id": plan.get("plan_id"), "version": plan.get("version")})
    except FileNotFoundError as exc:
        return tool_error("plan_close", str(exc), "NotFound")
    except RuntimeError as exc:
        return tool_error("plan_close", str(exc), "VersionConflict")
    except Exception as exc:
        return tool_error("plan_close", str(exc), type(exc).__name__)
