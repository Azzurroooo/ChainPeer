"""Status text rendering for CLI slash commands."""

from __future__ import annotations

from agent.interfaces.cli.formatting import display_value

from .router import SlashCommandContext


async def render_status(context: SlashCommandContext) -> str:
    session = context.session
    message_count = await _message_count(session)
    lines = [
        "```text",
        "Status:",
        f"Session: {display_value(getattr(session, 'session_id', None))}",
        f"Model: {display_value(getattr(session, 'model', None))}",
        f"Debug: {str(bool(context.debug)).lower()}",
        f"Messages: {message_count}",
    ]
    git_status = _git_status_line()
    if git_status:
        lines.append(git_status)
    latest_usage = await _latest_sampling_usage(session)
    if latest_usage:
        effective_window = int(latest_usage.get("effective_context_window_tokens") or 0)
        input_tokens = int(latest_usage.get("input_tokens") or 0)
        cached_tokens = int(latest_usage.get("cached_input_tokens") or 0)
        output_tokens = int(latest_usage.get("output_tokens") or 0)
        limit = f" / {_format_count(effective_window)}" if effective_window > 0 else ""
        lines.extend(
            [
                "",
                "Last sampling:",
                f"input: {_format_count(input_tokens)}{limit} ({_format_percent(latest_usage.get('context_usage_percent'))})",
                f"cached: {_format_count(cached_tokens)} ({_format_percent(latest_usage.get('cache_hit_rate'))})",
                f"output: {_format_count(output_tokens)}",
            ]
        )
    lines.append("```")
    return "\n".join(lines)


async def _message_count(session) -> str:
    get_messages = getattr(session, "get_messages_slice", None)
    if not callable(get_messages):
        return "unknown"
    try:
        return str(len(await get_messages()))
    except Exception:
        return "unknown"


def _git_status_line() -> str:
    try:
        from agent.interfaces.cli.ui import GitPromptStatusProvider

        status = GitPromptStatusProvider(ttl_seconds=0).current()
    except Exception:
        return ""
    if status is None:
        return ""
    marker = "*" if status.dirty else ""
    return f"Git: {status.branch}{marker}"


async def _latest_sampling_usage(session) -> dict | None:
    get_usage = getattr(session, "get_latest_sampling_usage", None)
    if not callable(get_usage):
        return None
    try:
        usage = await get_usage()
        return dict(usage) if isinstance(usage, dict) else None
    except Exception:
        return None


def _format_count(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        return f"{number / 1000:.1f}k"
    return str(int(number))


def _format_percent(value: object) -> str:
    if not isinstance(value, int | float):
        return "0.0%"
    return f"{value * 100:.1f}%"
