"""Human-readable summaries for tool activity lines."""

from __future__ import annotations

import json
from typing import Any


def tool_activity_summary(tool_name: str, args_preview: str = "", *, max_len: int = 120) -> str:
    name = str(tool_name or "unknown").strip() or "unknown"
    args = _parse_args(args_preview)
    detail = _tool_detail(name, args) if args else ""
    if not detail:
        return name
    return f"{name}: {_clip(detail, max_len)}"


def _parse_args(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_detail(name: str, args: dict[str, Any]) -> str:
    if name == "bash":
        return _string(args.get("command"))
    if name == "bash_output":
        bg_id = _string(args.get("bg_id"))
        return f"bg {bg_id}" if bg_id else ""
    if name in {"read_file", "write_file", "edit_file"}:
        return _string(args.get("file_path"))
    if name == "glob":
        pattern = _string(args.get("pattern"))
        path = _string(args.get("path"))
        return f"{pattern} in {path or '.'}" if pattern else path
    if name == "grep":
        pattern = _string(args.get("pattern"))
        path = _string(args.get("path")) or "."
        return f"{pattern} in {path}" if pattern else path
    if name == "list_files":
        return _string(args.get("directory")) or _string(args.get("pattern"))
    for key in ("path", "file_path", "query", "url", "command"):
        value = _string(args.get(key))
        if value:
            return value
    return ""


def _string(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


def _clip(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."
