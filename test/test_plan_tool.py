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
    plan_close,
    plan_create,
    plan_get,
    plan_link_dependency,
    plan_next,
    plan_reorder,
    plan_update_step,
)

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


def test_create_and_next() -> tuple[str, int]:
    payload = assert_ok(parse_payload(plan_create("P1", "goal", _steps())))
    data = payload.get("data") or {}
    if data.get("version") != 1:
        raise AssertionError(f"Expected version=1, got: {data}")
    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise AssertionError(f"Invalid plan_id: {data}")

    ready = assert_ok(parse_payload(plan_next("ready"))).get("data") or []
    ready_ids = {item.get("step_id") for item in ready}
    if ready_ids != {"s1", "s3"}:
        raise AssertionError(f"Expected ready steps s1/s3, got: {ready_ids}")

    focus = assert_ok(parse_payload(plan_next("focus"))).get("data") or {}
    if focus.get("step_id") != "s1":
        raise AssertionError(f"Expected focus s1 by priority, got: {focus}")
    return plan_id, int(data["version"])


def test_dependency_and_blocked(version: int) -> int:
    payload = parse_payload(plan_update_step("s2", {"status": "in_progress"}, expected_version=version))
    assert_error(payload, "DependencyViolation")

    payload = parse_payload(plan_update_step("s1", {"status": "blocked"}, expected_version=version))
    assert_error(payload, "ValidationError")

    blocked = assert_ok(
        parse_payload(plan_update_step("s1", {"status": "blocked", "blocked_reason": "need input"}, expected_version=version))
    ).get("meta")
    return int(blocked["version"])


def test_version_conflict(version: int) -> int:
    ok = assert_ok(parse_payload(plan_update_step("s1", {"status": "pending"}, expected_version=version)))
    new_version = int((ok.get("meta") or {}).get("version"))
    conflict = parse_payload(plan_update_step("s3", {"status": "in_progress"}, expected_version=version))
    assert_error(conflict, "VersionConflict")
    return new_version


def test_reorder_link_and_close(version: int) -> None:
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

        _, version = test_create_and_next()
        version = test_dependency_and_blocked(version)
        version = test_version_conflict(version)
        test_reorder_link_and_close(version)

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
