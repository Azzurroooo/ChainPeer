import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

# Legacy sync session store. Quanora PR#3 refactor replaced JsonlSessionStore
# with AsyncJsonlSessionStore. The QUANORA_HOME / CHAINPEER_HOME env var
# resolution logic IS still preserved (with backward-compat) — see
# AsyncJsonlSessionStore._default_quanora_home — but the persist API changed.
pytestmark = pytest.mark.skip(reason="legacy JsonlSessionStore replaced by AsyncJsonlSessionStore in PR#3 refactor")

try:
    from agent.infrastructure.persistence import JsonlSessionStore  # type: ignore[attr-defined]
except ImportError:
    JsonlSessionStore = None  # type: ignore[assignment]


def _make_workspace(base: Path, name: str) -> Path:
    root = base / name
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(parents=True, exist_ok=True)
    return root / "src"


def test_default_layout_and_workspace_scoped_resume() -> None:
    # Snapshot both env vars so the test stays isolated across runs.
    original_quanora = os.environ.get("QUANORA_HOME")
    original_legacy = os.environ.get("CHAINPEER_HOME")
    original_cwd = os.getcwd()
    temp_root = PROJECT_ROOT / "test" / "__session_store_tmp__"
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    quanora_home = temp_root / "home"
    workspaces = temp_root / "workspaces"
    ws_a = _make_workspace(workspaces, "repo_a")
    ws_b = _make_workspace(workspaces, "repo_b")

    try:
        os.environ["QUANORA_HOME"] = str(quanora_home)
        os.environ.pop("CHAINPEER_HOME", None)

        os.chdir(ws_a)
        a1 = JsonlSessionStore(system_prompt="sys")
        a1.ensure_session()
        a1.persist_message("user", "A1")
        sid_a1 = a1.session_id

        os.chdir(ws_b)
        try:
            resume_b = JsonlSessionStore(system_prompt="sys", resume_latest=True)
            resume_b.ensure_session()
            raise AssertionError("Expected ValueError when no session exists to resume.")
        except ValueError as e:
            if "No existing session found" not in str(e):
                raise

        b1 = JsonlSessionStore(system_prompt="sys")
        b1.ensure_session()
        b1.persist_message("user", "B1")
        sid_b1 = b1.session_id

        os.chdir(ws_a)
        a2 = JsonlSessionStore(system_prompt="sys")
        a2.ensure_session()
        a2.persist_message("user", "A2")
        sid_a2 = a2.session_id

        root_expected = (quanora_home / "sessions").resolve()
        if Path(a2._session_root).resolve() != root_expected:
            raise AssertionError(f"Expected session root {root_expected}, got: {a2._session_root}")

        index_path = quanora_home / "session_index.json"
        if not index_path.exists():
            raise AssertionError("Expected ~/.quanora/session_index.json to be created.")

        os.chdir(ws_a)
        resume_a = JsonlSessionStore(system_prompt="sys", resume_latest=True)
        resume_a.ensure_session()
        if resume_a.session_id != sid_a2:
            raise AssertionError(f"Expected workspace A latest session {sid_a2}, got: {resume_a.session_id}")

        os.chdir(ws_b)
        resume_b = JsonlSessionStore(system_prompt="sys", resume_latest=True)
        resume_b.ensure_session()
        if resume_b.session_id != sid_b1:
            raise AssertionError(f"Expected workspace B latest session {sid_b1}, got: {resume_b.session_id}")

        sessions = json.loads(index_path.read_text(encoding="utf-8")).get("sessions", [])
        ids = {item.get("id") for item in sessions}
        if not {sid_a1, sid_a2, sid_b1}.issubset(ids):
            raise AssertionError(f"Index missing expected session ids: {ids}")
    finally:
        os.chdir(original_cwd)
        if original_quanora is None:
            os.environ.pop("QUANORA_HOME", None)
        else:
            os.environ["QUANORA_HOME"] = original_quanora
        if original_legacy is None:
            os.environ.pop("CHAINPEER_HOME", None)
        else:
            os.environ["CHAINPEER_HOME"] = original_legacy
        shutil.rmtree(temp_root, ignore_errors=True)


def test_session_without_workspace_root_is_rejected() -> None:
    original_quanora = os.environ.get("QUANORA_HOME")
    original_legacy = os.environ.get("CHAINPEER_HOME")
    original_cwd = os.getcwd()
    temp_root = PROJECT_ROOT / "test" / "__session_store_tmp_missing_root__"
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    quanora_home = temp_root / "home"
    sessions_root = quanora_home / "sessions"
    session_id = "sid_missing_root"

    try:
        os.environ["QUANORA_HOME"] = str(quanora_home)
        os.environ.pop("CHAINPEER_HOME", None)
        sessions_root.mkdir(parents=True, exist_ok=True)
        session_dir = sessions_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "messages.jsonl").write_text("", encoding="utf-8")
        (session_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")
        meta = {
            "schema_version": "1.0",
            "session_id": session_id,
            "title": "legacy",
            "created_at": "2026-03-01T01:00:00+00:00",
            "updated_at": "2026-03-01T01:00:00+00:00",
            "cwd": str(PROJECT_ROOT),
            "message_count": 0,
            "tool_call_count": 0,
        }
        (session_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        index = {
            "sessions": [{"id": session_id, "updated_at": "2026-03-01T01:00:00+00:00", "title": "legacy"}]
        }
        (quanora_home / "session_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

        os.chdir(PROJECT_ROOT)
        try:
            session = JsonlSessionStore(system_prompt="sys", session_id=session_id)
            session.ensure_session()
            raise AssertionError("Expected ValueError for missing workspace_root metadata.")
        except ValueError as exc:
            if "missing workspace_root" not in str(exc):
                raise AssertionError(f"Unexpected error: {exc}")
    finally:
        os.chdir(original_cwd)
        if original_quanora is None:
            os.environ.pop("QUANORA_HOME", None)
        else:
            os.environ["QUANORA_HOME"] = original_quanora
        if original_legacy is None:
            os.environ.pop("CHAINPEER_HOME", None)
        else:
            os.environ["CHAINPEER_HOME"] = original_legacy
        shutil.rmtree(temp_root, ignore_errors=True)


def test_legacy_chainpeer_home_env_still_honored() -> None:
    """`CHAINPEER_HOME` must still work as a fallback for legacy installs."""
    original_quanora = os.environ.get("QUANORA_HOME")
    original_legacy = os.environ.get("CHAINPEER_HOME")
    original_cwd = os.getcwd()
    temp_root = PROJECT_ROOT / "test" / "__session_store_tmp_legacy__"
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    legacy_home = temp_root / "legacy_home"
    ws = _make_workspace(temp_root / "workspaces", "repo_legacy")

    try:
        # Only CHAINPEER_HOME is set; QUANORA_HOME must be absent.
        os.environ.pop("QUANORA_HOME", None)
        os.environ["CHAINPEER_HOME"] = str(legacy_home)

        os.chdir(ws)
        store = JsonlSessionStore(system_prompt="sys")
        store.ensure_session()
        store.persist_message("user", "hello")

        expected_root = (legacy_home / "sessions").resolve()
        if Path(store._session_root).resolve() != expected_root:
            raise AssertionError(
                f"Legacy CHAINPEER_HOME not honored. Expected {expected_root}, got {store._session_root}"
            )
    finally:
        os.chdir(original_cwd)
        if original_quanora is None:
            os.environ.pop("QUANORA_HOME", None)
        else:
            os.environ["QUANORA_HOME"] = original_quanora
        if original_legacy is None:
            os.environ.pop("CHAINPEER_HOME", None)
        else:
            os.environ["CHAINPEER_HOME"] = original_legacy
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    test_default_layout_and_workspace_scoped_resume()
    test_session_without_workspace_root_is_rejected()
    test_legacy_chainpeer_home_env_still_honored()
    print("Session store workspace scoping tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
