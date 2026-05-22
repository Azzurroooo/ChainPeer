"""Plan scheduling helpers."""

from __future__ import annotations

from typing import Any

from .helpers import dependency_depth
from .model import TERMINAL_STEP_STATUS, all_deps_completed, assert_expected_version, ensure_plan_defaults, step_map
from .store import load_plan


def next_steps(mode: str, expected_version: int | None = None) -> tuple[Any, dict[str, Any]]:
    plan, _, _ = load_plan()
    ensure_plan_defaults(plan)
    if expected_version is not None:
        assert_expected_version(plan, expected_version)
    if mode not in {"ready", "focus", "blocked_report"}:
        raise ValueError("mode must be one of: ready, focus, blocked_report.")

    step_by_id = step_map(plan)
    ordered = sorted(step_by_id.values(), key=lambda item: int(item.get("order", 0)))
    ready = [step for step in ordered if step.get("status") == "pending" and all_deps_completed(step, step_by_id)]
    meta = {"plan_id": plan.get("plan_id"), "version": plan.get("version")}

    if mode == "ready":
        return ready, {**meta, "count": len(ready)}
    if mode == "blocked_report":
        blocked = _blocked_report(ordered, step_by_id)
        return blocked, {**meta, "count": len(blocked)}
    if not ready:
        reason = "all_steps_terminal" if ordered and all(step.get("status") in TERMINAL_STEP_STATUS for step in ordered) else "no_ready_steps"
        return None, {**meta, "reason": reason}
    return _focus_step(ready, step_by_id), {**meta, "mode": "focus"}


def _blocked_report(ordered: list[dict[str, Any]], step_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for step in ordered:
        if step.get("status") == "blocked":
            blocked.append({"step_id": step["step_id"], "reason": step.get("blocked_reason") or "blocked"})
            continue
        if step.get("status") == "pending":
            deps = step.get("depends_on") or []
            missing = [dep for dep in deps if dep in step_by_id and step_by_id[dep].get("status") != "completed"]
            if missing:
                blocked.append({"step_id": step["step_id"], "reason": "waiting_dependencies", "blocked_by": missing})
    return blocked


def _focus_step(ready: list[dict[str, Any]], step_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    memo: dict[str, int] = {}
    return sorted(
        ready,
        key=lambda item: (
            -int(item.get("priority", 0)),
            dependency_depth(item["step_id"], step_by_id, memo),
            int(item.get("order", 0)),
        ),
    )[0]
