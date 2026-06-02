"""Prompt text and bottom toolbar for the interactive CLI."""

from __future__ import annotations

from pathlib import Path


def prompt_message() -> str:
    return "\nYou > "


def prompt_continuation(width: int, line_number: int, is_soft_wrap: bool) -> str:
    return "  ... "


def prompt_toolbar(
    session,
    *,
    debug: bool = False,
    cwd: str | Path | None = None,
    usage: dict[str, object] | None = None,
) -> str:
    items = [
        f"session {_short_session_id(getattr(session, 'session_id', None))}",
        f"model {_clip(_value(getattr(session, 'model', None)), 26)}",
    ]
    usage_text = _usage_summary(usage)
    if usage_text:
        items.append(usage_text)
    items.append(f"cwd {_clip(_cwd_name(cwd), 28)}")
    if debug:
        items.append("debug on")
    items.extend(["Enter send", "Ctrl+J newline", "Tab complete /commands", "Ctrl+C interrupt"])
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


def _usage_summary(usage: dict[str, object] | None) -> str:
    if not isinstance(usage, dict):
        return ""

    items = []
    context = _format_percent(usage.get("context_usage_percent"))
    if context:
        items.append(f"ctx {context}")
    else:
        input_tokens = _number(usage.get("input_tokens"))
        window = _number(usage.get("effective_context_window_tokens"))
        if input_tokens is not None and window:
            items.append(f"ctx {_format_count(input_tokens)}/{_format_count(window)}")
        elif input_tokens is not None:
            items.append(f"ctx {_format_count(input_tokens)}")

    cache = _format_percent(usage.get("cache_hit_rate"))
    if cache:
        items.append(f"cache {cache}")
    return " ".join(items)


def _format_percent(value: object) -> str:
    number = _number(value)
    if number is None:
        return ""
    percent = number * 100 if abs(number) <= 1 else number
    return f"{percent:.1f}%"


def _format_count(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    return str(int(value))


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
