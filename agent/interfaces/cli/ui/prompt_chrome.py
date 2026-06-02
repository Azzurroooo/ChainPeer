"""Prompt text and bottom toolbar for the interactive CLI."""

from __future__ import annotations

from pathlib import Path


def prompt_message() -> str:
    return "\nYou > "


def prompt_continuation(width: int, line_number: int, is_soft_wrap: bool) -> str:
    return "  ... "


def prompt_toolbar(session, *, debug: bool = False, cwd: str | Path | None = None) -> str:
    items = [
        f"session {_short_session_id(getattr(session, 'session_id', None))}",
        f"model {_clip(_value(getattr(session, 'model', None)), 26)}",
        f"cwd {_clip(_cwd_name(cwd), 28)}",
    ]
    if debug:
        items.append("debug on")
    items.extend(["Enter send", "Ctrl+J newline", "/help commands", "Ctrl+C interrupt"])
    return "  |  ".join(items)


def _short_session_id(value: object) -> str:
    text = _value(value)
    if text == "unknown" or len(text) <= 14:
        return text
    return f"{text[:8]}...{text[-4:]}"


def _cwd_name(cwd: str | Path | None) -> str:
    path = Path(cwd) if cwd else Path.cwd()
    name = path.name or str(path)
    return name or "unknown"


def _value(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _clip(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."
