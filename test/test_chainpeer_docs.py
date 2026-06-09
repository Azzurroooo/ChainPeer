import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.infrastructure.chainpeer_docs import (
    CHAINPEER_DOC_BYTE_LIMIT,
    build_chainpeer_doc_context,
    resolve_project_doc_path,
    resolve_user_doc_path,
)


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_chainpeer_docs_inject_user_before_project(tmp_path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    project = _project_root(tmp_path)
    user_home.mkdir()
    monkeypatch.setenv("CHAINPEER_HOME", str(user_home))
    monkeypatch.chdir(project)
    (user_home / "CHAINPEER.md").write_text("user guidance", encoding="utf-8")
    (project / "CHAINPEER.md").write_text("project guidance", encoding="utf-8")

    messages, stats, decisions = build_chainpeer_doc_context()
    content = messages[0]["content"]

    assert content.index("--- user-doc ---") < content.index("--- project-doc ---")
    assert "user guidance" in content
    assert "project guidance" in content
    assert stats["chainpeer_docs_user_exists"] is True
    assert stats["chainpeer_docs_project_exists"] is True
    assert decisions["chainpeer_docs_injected"] is True
    assert decisions["chainpeer_docs_truncated"] is False


def test_chainpeer_docs_skip_missing_levels(tmp_path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    project = _project_root(tmp_path)
    user_home.mkdir()
    monkeypatch.setenv("CHAINPEER_HOME", str(user_home))
    monkeypatch.chdir(project)
    (project / "CHAINPEER.md").write_text("project only", encoding="utf-8")

    messages, stats, decisions = build_chainpeer_doc_context()
    content = messages[0]["content"]

    assert "--- user-doc ---" not in content
    assert content.startswith("\n\n--- project-doc ---\n\n")
    assert "project only" in content
    assert stats["chainpeer_docs_user_exists"] is False
    assert decisions["chainpeer_docs_injected"] is True


def test_chainpeer_docs_do_not_inject_when_absent(tmp_path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    project = _project_root(tmp_path)
    user_home.mkdir()
    monkeypatch.setenv("CHAINPEER_HOME", str(user_home))
    monkeypatch.chdir(project)

    messages, stats, decisions = build_chainpeer_doc_context()

    assert messages == []
    assert stats["chainpeer_docs_user_exists"] is False
    assert stats["chainpeer_docs_project_exists"] is False
    assert decisions["chainpeer_docs_injected"] is False


def test_chainpeer_docs_truncate_by_utf8_bytes(tmp_path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    project = _project_root(tmp_path)
    user_home.mkdir()
    monkeypatch.setenv("CHAINPEER_HOME", str(user_home))
    monkeypatch.chdir(project)
    raw = b"a" * (CHAINPEER_DOC_BYTE_LIMIT - 1) + "你".encode("utf-8")
    (user_home / "CHAINPEER.md").write_bytes(raw)

    messages, stats, decisions = build_chainpeer_doc_context()
    content = messages[0]["content"]

    assert "was truncated before injection" in content
    assert "\ufffd" not in content
    assert stats["chainpeer_docs_user_bytes"] == len(raw)
    assert stats["chainpeer_docs_user_injected_bytes"] <= CHAINPEER_DOC_BYTE_LIMIT
    assert decisions["chainpeer_docs_truncated"] is True
    assert decisions["chainpeer_docs_truncated_scopes"] == ["user"]


def test_chainpeer_doc_paths_use_configured_home_and_project_root(tmp_path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    project = _project_root(tmp_path)
    nested = project / "src" / "pkg"
    nested.mkdir(parents=True)
    monkeypatch.setenv("CHAINPEER_HOME", str(user_home))
    monkeypatch.chdir(nested)

    assert resolve_user_doc_path() == user_home.resolve() / "CHAINPEER.md"
    assert resolve_project_doc_path() == project.resolve() / "CHAINPEER.md"

