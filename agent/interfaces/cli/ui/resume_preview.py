"""Compact resume preview for loaded conversations."""

from __future__ import annotations

import re


DEFAULT_RESUME_PREVIEW_LIMIT = 6
DEFAULT_RESUME_PREVIEW_CHARS = 180


def render_resume_preview(
    messages: list[dict],
    *,
    session_id: str | None = None,
    limit: int = DEFAULT_RESUME_PREVIEW_LIMIT,
    preview_chars: int = DEFAULT_RESUME_PREVIEW_CHARS,
) -> str:
    visible = [
        (str(message.get("role") or ""), str(message.get("content") or ""))
        for message in messages
        if isinstance(message, dict)
        and message.get("role") in {"user", "assistant"}
        and str(message.get("content") or "").strip()
    ]
    if not visible:
        return ""

    shown = visible[-max(1, limit) :]
    hidden = max(0, len(visible) - len(shown))
    lines = [
        (
            f"Resumed session {_short_id(session_id)}: "
            f"{len(visible)} visible message(s), showing last {len(shown)}."
        )
    ]
    if hidden:
        lines.append(f"Full context is still loaded; {hidden} older message(s) are hidden from the terminal.")
    for role, content in shown:
        lines.append(f"- {role}: {_preview(content, preview_chars)}")
    lines.append("Use /status for details, /sessions to switch, or continue typing below.")
    return "\n".join(lines)


def _preview(content: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _short_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 18:
        return text
    return f"{text[:10]}...{text[-4:]}"
