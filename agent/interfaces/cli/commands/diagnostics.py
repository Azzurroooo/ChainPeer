"""Read-only CLI diagnostics for common setup problems."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .router import SlashCommandContext


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    status: str
    name: str
    detail: str


def render_doctor_report(context: SlashCommandContext) -> str:
    checks = _build_checks(context)
    failures = sum(1 for check in checks if check.status == "fail")
    warnings = sum(1 for check in checks if check.status == "warn")
    lines = ["Doctor:"]
    lines.extend(f"- [{check.status}] {check.name}: {check.detail}" for check in checks)
    lines.append(f"Overall: {failures} failure(s), {warnings} warning(s).")
    next_steps = _next_steps(checks)
    if next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {step}" for step in next_steps)
    return "\n".join(lines)


def _build_checks(context: SlashCommandContext) -> list[DoctorCheck]:
    from agent.infrastructure.config import Config

    checks = [
        _python_check(),
        _working_directory_check(),
        _git_check(),
        _settings_check(Config),
        _api_key_check(Config),
        _model_check(Config),
        _context_window_check(Config),
        _session_store_check(context),
        _shell_check(),
    ]
    return checks


def _python_check() -> DoctorCheck:
    version = platform.python_version()
    if sys.version_info >= (3, 12):
        return DoctorCheck("ok", "Python", version)
    return DoctorCheck("fail", "Python", f"{version} (requires 3.12+)")


def _working_directory_check() -> DoctorCheck:
    cwd = Path.cwd()
    if cwd.exists() and cwd.is_dir():
        return DoctorCheck("ok", "Working directory", str(cwd))
    return DoctorCheck("fail", "Working directory", f"{cwd} is not available")


def _git_check() -> DoctorCheck:
    git = shutil.which("git")
    if not git:
        return DoctorCheck("warn", "Git", "not found on PATH")
    branch = _run_git(["branch", "--show-current"])
    if branch is None:
        return DoctorCheck("warn", "Git", "not a git worktree")
    dirty = _run_git(["status", "--short"])
    suffix = "clean" if not dirty else f"{len(dirty.splitlines())} change(s)"
    return DoctorCheck("ok", "Git", f"{branch or 'detached HEAD'} ({suffix})")


def _settings_check(config) -> DoctorCheck:
    path = str(getattr(config, "SETTINGS_PATH", "") or "unknown")
    state = "found" if bool(getattr(config, "SETTINGS_EXISTS", False)) else "missing"
    status = "ok" if state == "found" else "warn"
    return DoctorCheck(status, "Settings", f"{path} ({state})")


def _api_key_check(config) -> DoctorCheck:
    if getattr(config, "OPENAI_API_KEY", ""):
        return DoctorCheck("ok", "API key", "set")
    return DoctorCheck("fail", "API key", "unset")


def _model_check(config) -> DoctorCheck:
    model = str(getattr(config, "DEFAULT_MODEL", "") or "").strip()
    if model:
        return DoctorCheck("ok", "Model", model)
    return DoctorCheck("fail", "Model", "unset")


def _context_window_check(config) -> DoctorCheck:
    window = _safe_int(getattr(config, "CONTEXT_WINDOW_TOKENS", None))
    percent = _safe_int(getattr(config, "EFFECTIVE_CONTEXT_WINDOW_PERCENT", None))
    if window <= 0:
        return DoctorCheck("warn", "Context window", "unset")
    if percent <= 0 or percent > 100:
        return DoctorCheck("warn", "Context window", f"{window} tokens, invalid effective percent {percent}")
    return DoctorCheck("ok", "Context window", f"{window} tokens at {percent}% effective budget")


def _session_store_check(context: SlashCommandContext) -> DoctorCheck:
    path = _session_root(context.session)
    if not path:
        return DoctorCheck("warn", "Session store", "unknown")
    writable_target = _nearest_existing_parent(path)
    if writable_target and os.access(str(writable_target), os.W_OK):
        state = "ready" if path.exists() else f"will create under {writable_target}"
        return DoctorCheck("ok", "Session store", f"{path} ({state})")
    return DoctorCheck("fail", "Session store", f"{path} is not writable")


def _shell_check() -> DoctorCheck:
    shell = os.environ.get("SHELL") or os.environ.get("ComSpec") or os.environ.get("PSModulePath")
    if shell:
        return DoctorCheck("ok", "Shell", _shorten(str(shell)))
    return DoctorCheck("warn", "Shell", "not detected")


def _session_root(session) -> Path | None:
    raw_root = getattr(session, "_session_root", None)
    if raw_root:
        return Path(str(raw_root)).expanduser()
    raw_dir = getattr(session, "_session_dir", None)
    try:
        from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore

        return Path(AsyncJsonlSessionStore.resolve_session_root(str(raw_dir) if raw_dir else None))
    except Exception:
        return Path(str(raw_dir)).expanduser() if raw_dir else None


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return current


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _next_steps(checks: list[DoctorCheck]) -> list[str]:
    steps = []
    names = {check.name: check for check in checks if check.status in {"fail", "warn"}}
    if "API key" in names:
        steps.append("Set apiKey in settings.json or export OPENAI_API_KEY.")
    if "Settings" in names:
        steps.append("Run the CLI once to create the default settings template.")
    if "Session store" in names:
        steps.append("Choose a writable --session-dir or fix permissions for the session directory.")
    if "Python" in names:
        steps.append("Install Python 3.12 or newer.")
    return steps


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _shorten(value: str, limit: int = 90) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"...{text[-limit + 3:]}"
