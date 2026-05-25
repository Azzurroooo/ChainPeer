import json
import os
import shutil
import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.infrastructure.tools.impl.tools.plan import (
    plan_add_step,
    plan_close,
    plan_create,
    plan_get,
    plan_link_dependency,
    plan_next,
    plan_reorder,
    plan_update_meta,
    plan_update_step,
)
from agent.infrastructure.tools.impl import TOOLS, TOOL_SCHEMAS

@pytest.fixture(autouse=True)
def setup_session(tmp_path: Path):
    os.environ["AGENT_SESSION_ROOT"] = str(tmp_path)
    os.environ["AGENT_SESSION_ID"] = "test_plan_session"
    # Ensure the directory exists
    session_dir = tmp_path / "test_plan_session"
    session_dir.mkdir(parents=True, exist_ok=True)
    yield
    os.environ.pop("AGENT_SESSION_ROOT", None)
    os.environ.pop("AGENT_SESSION_ID", None)


def parse_payload(raw: str) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise AssertionError(f"Invalid payload: {raw}")
    return obj


def assert_ok(payload: dict) -> dict:
    if payload.get("ok") is not True:
        raise AssertionError(f"Expected ok=True, got: {payload}")
    return payload


def assert_error(payload: dict, error_type: str) -> dict:
    if payload.get("ok") is not False:
        raise AssertionError(f"Expected ok=False, got: {payload}")
    if payload.get("error_type") != error_type:
        raise AssertionError(f"Expected error_type={error_type}, got: {payload}")
    return payload


def _steps() -> list[dict]:
    return [
        {"step_id": "s1", "title": "analyze", "priority": 5},
        {"step_id": "s2", "title": "fix", "depends_on": ["s1"], "priority": 3},
        {"step_id": "s3", "title": "docs", "priority": 1},
    ]


def create_and_next() -> tuple[str, int]:
    payload = assert_ok(
        parse_payload(
            plan_create(
                "P1",
                "goal",
                _steps(),
                objectives=[{"metric": "sharpe", "operator": ">=", "target": 3.0}],
                constraints=[{"metric": "max_drawdown", "operator": "<=", "target": 0.12}],
            )
        )
    )
    data = payload.get("data") or {}
    if data.get("version") != 1:
        raise AssertionError(f"Expected version=1, got: {data}")
    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise AssertionError(f"Invalid plan_id: {data}")
    if "metrics" in data or "observations" in data:
        raise AssertionError(f"Plan should not contain fact-memory fields, got: {data}")

    ready = assert_ok(parse_payload(plan_next("ready"))).get("data") or []
    ready_ids = {item.get("step_id") for item in ready}
    if ready_ids != {"s1", "s3"}:
        raise AssertionError(f"Expected ready steps s1/s3, got: {ready_ids}")

    focus = assert_ok(parse_payload(plan_next("focus"))).get("data") or {}
    if focus.get("step_id") != "s1":
        raise AssertionError(f"Expected focus s1 by priority, got: {focus}")
    return plan_id, int(data["version"])


def dependency_and_blocked(version: int) -> int:
    payload = parse_payload(plan_update_step("s2", {"status": "in_progress"}, expected_version=version))
    assert_error(payload, "DependencyViolation")

    payload = parse_payload(plan_update_step("s1", {"status": "blocked"}, expected_version=version))
    assert_error(payload, "ValidationError")

    blocked = assert_ok(
        parse_payload(plan_update_step("s1", {"status": "blocked", "blocked_reason": "need input"}, expected_version=version))
    ).get("meta")
    return int(blocked["version"])


def version_conflict(version: int) -> int:
    ok = assert_ok(parse_payload(plan_update_step("s1", {"status": "pending"}, expected_version=version)))
    new_version = int((ok.get("meta") or {}).get("version"))
    conflict = parse_payload(plan_update_step("s3", {"status": "in_progress"}, expected_version=version))
    assert_error(conflict, "VersionConflict")
    return new_version


def reorder_link_and_close(version: int) -> None:
    payload = assert_ok(parse_payload(plan_reorder(["s3", "s1", "s2"], expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))

    payload = assert_ok(parse_payload(plan_link_dependency("s3", ["s1"], expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))

    cannot_close = parse_payload(plan_close("done", expected_version=version))
    assert_error(cannot_close, "DependencyViolation")

    payload = assert_ok(parse_payload(plan_update_step("s1", {"status": "in_progress"}, expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))
    payload = assert_ok(parse_payload(plan_update_step("s1", {"status": "completed"}, expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))
    payload = assert_ok(parse_payload(plan_update_step("s2", {"status": "in_progress"}, expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))
    payload = assert_ok(parse_payload(plan_update_step("s2", {"status": "completed"}, expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))
    payload = assert_ok(parse_payload(plan_update_step("s3", {"status": "in_progress"}, expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))
    payload = assert_ok(parse_payload(plan_update_step("s3", {"status": "completed"}, expected_version=version)))
    version = int((payload.get("meta") or {}).get("version"))

    closed = assert_ok(parse_payload(plan_close("all done", expected_version=version)))
    if (closed.get("data") or {}).get("status") != "completed":
        raise AssertionError(f"Expected completed plan, got: {closed}")

    current = assert_ok(parse_payload(plan_get())).get("data") or {}
    if current.get("summary") != "all done":
        raise AssertionError(f"Expected summary updated, got: {current}")


def test_plan_tool_flow() -> None:
    _, version = create_and_next()
    version = dependency_and_blocked(version)
    version = version_conflict(version)
    reorder_link_and_close(version)


def test_iterative_plan_tools(tmp_path: Path) -> None:
    payload = assert_ok(parse_payload(plan_create("Iter", "Optimize strategy", [{"step_id": "s1", "title": "baseline"}])))
    version = int(payload["data"]["version"])

    added = assert_ok(
        parse_payload(
            plan_add_step(
                title="test volatility filter",
                depends_on=["s1"],
                priority=4,
                acceptance="Sharpe improves without drawdown breach",
                expected_version=version,
            )
        )
    )
    version = int(added["meta"]["version"])
    if (added.get("data") or {}).get("step_id") != "step_2":
        raise AssertionError(f"Expected generated step_2, got: {added}")

    duplicate = parse_payload(plan_add_step(title="duplicate", step_id="s1", expected_version=version))
    assert_error(duplicate, "ValidationError")

    unknown_dep = parse_payload(plan_add_step(title="unknown", depends_on=["missing"], expected_version=version))
    assert_error(unknown_dep, "DependencyViolation")

    meta = assert_ok(
        parse_payload(
            plan_update_meta(
                expected_version=version,
                goal="Optimize to CAGR >= 10% and Sharpe >= 3",
                objectives=[{"metric": "sharpe", "operator": ">=", "target": 3.0}],
                constraints=[{"metric": "max_drawdown", "operator": "<=", "target": 0.12}],
            )
        )
    )
    version = int(meta["meta"]["version"])
    data = meta.get("data") or {}
    if "metrics" in data or "observation_count" in data:
        raise AssertionError(f"Plan meta should not expose fact-memory fields, got: {data}")

    current = assert_ok(parse_payload(plan_get())).get("data") or {}
    if "metrics" in current or "observations" in current:
        raise AssertionError(f"Plan should not contain fact-memory fields, got: {current}")

    events = tmp_path / "test_plan_session" / "plan_events.jsonl"
    content = events.read_text(encoding="utf-8")
    if "observation_recorded" in content:
        raise AssertionError(f"Did not expect observation events, got: {content}")
    if "step_added" not in content or "plan_meta_updated" not in content:
        raise AssertionError(f"Expected iterative events, got: {content}")


def test_plan_schema_excludes_observation_and_metrics() -> None:
    if "plan_record_observation" in TOOLS:
        raise AssertionError("plan_record_observation should not be registered.")
    schemas = {item["function"]["name"]: item["function"] for item in TOOL_SCHEMAS}
    if "plan_record_observation" in schemas:
        raise AssertionError("plan_record_observation schema should not be registered.")
    for name in ("plan_create", "plan_update_meta"):
        props = ((schemas.get(name) or {}).get("parameters") or {}).get("properties") or {}
        if "metrics" in props:
            raise AssertionError(f"{name} schema should not contain metrics: {props}")


def test_plan_next_all_steps_terminal() -> None:
    payload = assert_ok(parse_payload(plan_create("Terminal", "goal", [{"step_id": "s1", "title": "one"}])))
    version = int(payload["data"]["version"])
    payload = assert_ok(parse_payload(plan_update_step("s1", {"status": "in_progress"}, expected_version=version)))
    version = int(payload["meta"]["version"])
    payload = assert_ok(parse_payload(plan_update_step("s1", {"status": "completed"}, expected_version=version)))
    version = int(payload["meta"]["version"])

    focus = assert_ok(parse_payload(plan_next("focus", expected_version=version)))
    if (focus.get("meta") or {}).get("reason") != "all_steps_terminal":
        raise AssertionError(f"Expected terminal reason, got: {focus}")

    closed = assert_ok(parse_payload(plan_close("done", expected_version=version)))
    version = int(closed["meta"]["version"])
    rejected = parse_payload(plan_add_step(title="after close", expected_version=version))
    assert_error(rejected, "ValidationError")


def main() -> int:
    temp_root = PROJECT_ROOT / "test" / "__plan_tool_tmp_sessions__"
    sid = "sid_test_plan"
    base = temp_root / sid
    original_root = os.environ.get("AGENT_SESSION_ROOT")
    original_sid = os.environ.get("AGENT_SESSION_ID")

    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.environ["AGENT_SESSION_ROOT"] = str(temp_root)
        os.environ["AGENT_SESSION_ID"] = sid

        _, version = create_and_next()
        version = dependency_and_blocked(version)
        version = version_conflict(version)
        reorder_link_and_close(version)

        events = base / "plan_events.jsonl"
        if not events.exists():
            raise AssertionError("Expected plan_events.jsonl to be created.")
        if len(events.read_text(encoding="utf-8").splitlines()) < 3:
            raise AssertionError("Expected multiple plan events.")
        print("All plan tool tests passed.")
        return 0
    finally:
        if original_root is None:
            os.environ.pop("AGENT_SESSION_ROOT", None)
        else:
            os.environ["AGENT_SESSION_ROOT"] = original_root
        if original_sid is None:
            os.environ.pop("AGENT_SESSION_ID", None)
        else:
            os.environ["AGENT_SESSION_ID"] = original_sid
        try:
            shutil.rmtree(temp_root, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
