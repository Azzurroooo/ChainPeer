"""Handlers for CLI slash commands."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .router import SlashCommandContext, SlashCommandResult


def default_handlers() -> dict[str, Callable]:
    return {
        "help": handle_help,
        "status": handle_status,
        "doctor": handle_doctor,
        "sessions": handle_sessions,
        "skill": handle_skill,
        "plan": handle_plan,
        "compact": handle_compact,
        "model": handle_model,
        "login": handle_login,
        "config": handle_config,
        "exit": handle_exit,
        "quit": handle_exit,
    }


async def handle_help(context: SlashCommandContext, args: list[str]) -> str:
    return "\n".join(
        [
            "Available commands:",
            "/help      Show commands",
            "/status    Show session status",
            "/doctor    Run local setup diagnostics",
            "/sessions  List recent sessions",
            "/skill     List skills",
            "/plan      Show active plan summary",
            "/compact   Compact current session context",
            "/model     Show current model",
            "/login     Show login setup guidance",
            "/config    Show config guidance",
            "/exit      Exit CLI",
        ]
    )


async def handle_status(context: SlashCommandContext, args: list[str]) -> str:
    session = context.session
    message_count = "unknown"
    get_messages = getattr(session, "get_messages_slice", None)
    if callable(get_messages):
        try:
            message_count = str(len(await get_messages()))
        except Exception:
            message_count = "unknown"
    lines = [
        "Status:",
        f"- Session: {_value(getattr(session, 'session_id', None))}",
        f"- Model: {_value(getattr(session, 'model', None))}",
        f"- Debug: {str(bool(context.debug)).lower()}",
        f"- Messages: {message_count}",
    ]
    latest_usage = await _latest_sampling_usage(session)
    if latest_usage:
        effective_window = int(latest_usage.get("effective_context_window_tokens") or 0)
        input_tokens = int(latest_usage.get("input_tokens") or 0)
        cached_tokens = int(latest_usage.get("cached_input_tokens") or 0)
        output_tokens = int(latest_usage.get("output_tokens") or 0)
        limit = f" / {_format_count(effective_window)}" if effective_window > 0 else ""
        lines.extend(
            [
                "Last sampling:",
                f"- input: {_format_count(input_tokens)}{limit} ({_format_percent(latest_usage.get('context_usage_percent'))})",
                f"- cached: {_format_count(cached_tokens)} ({_format_percent(latest_usage.get('cache_hit_rate'))})",
                f"- output: {_format_count(output_tokens)}",
            ]
        )
    return "\n".join(lines)


async def handle_doctor(context: SlashCommandContext, args: list[str]) -> str:
    if args:
        return "Usage: /doctor"
    from .diagnostics import render_doctor_report

    return render_doctor_report(context)


async def handle_sessions(context: SlashCommandContext, args: list[str]) -> str:
    limit = _parse_limit(args, default=8, maximum=20)
    if limit is None:
        return "Usage: /sessions [limit]"
    list_sessions = getattr(context.session, "list_recent_sessions", None)
    if not callable(list_sessions):
        return "Sessions are not supported by this session store."
    try:
        sessions = await list_sessions(limit=limit)
    except TypeError:
        sessions = await list_sessions()
    except Exception as exc:
        return f"Command failed: {exc}"
    if not sessions:
        return "No recent sessions."

    current_id = str(getattr(context.session, "session_id", "") or "")
    lines = ["Recent sessions:"]
    for item in sessions[:limit]:
        if not isinstance(item, dict):
            continue
        session_id = _value(item.get("id"))
        marker = " (current)" if current_id and session_id == current_id else ""
        updated = _value(item.get("updated_at"))
        title = _truncate(_value(item.get("title")), 40)
        size = _format_session_size(item.get("size"))
        preview = _truncate(str(item.get("preview") or "").replace("\n", " ").strip(), 56)
        suffix = f" | {preview}" if preview else ""
        lines.append(f"- {session_id}{marker} | {updated} | {title} | {size}{suffix}")
    lines.append("Resume with: python main.py --session <id>")
    return "\n".join(lines)


async def handle_skill(context: SlashCommandContext, args: list[str]) -> str:
    if args and args[0].lower() != "list":
        return "Usage: /skill or /skill list"
    try:
        from agent.infrastructure.skills.skill_repository import SkillRepository

        skills = SkillRepository(project_root=str(Path.cwd())).list_skills()
    except Exception as exc:
        return f"Command failed: {exc}"
    if not skills:
        return "No skills found."
    lines = ["Skills:"]
    for skill in skills:
        description = str(getattr(skill, "description", "") or "").strip()
        path = str(getattr(skill, "path", "") or "")
        lines.append(f"- {skill.name} [{skill.source}] {description} ({path})")
    return "\n".join(lines)


async def handle_plan(context: SlashCommandContext, args: list[str]) -> str:
    try:
        from agent.infrastructure.plans.store import load_plan_if_exists
        from agent.infrastructure.plans.summary import render_compact_plan_summary

        plan = load_plan_if_exists()
        summary = render_compact_plan_summary(plan) if plan else ""
    except FileNotFoundError:
        summary = ""
    except Exception as exc:
        return f"Command failed: {exc}"
    return summary or "No active plan."


async def handle_compact(context: SlashCommandContext, args: list[str]) -> str:
    compact_context = getattr(context.runtime, "compact_context", None)
    if callable(compact_context):
        try:
            record = await compact_context(reason="manual")
        except TypeError:
            record = await compact_context()
    else:
        compact_context = getattr(context.session, "compact_context", None)
        if not callable(compact_context):
            return "Compact is not supported by this session store."
        record = await compact_context()
    source = record.get("source") if isinstance(record, dict) else {}
    if not isinstance(source, dict):
        source = {}
    start = source.get("message_start_index", "?")
    end = source.get("message_end_index_exclusive", "?")
    tool_count = len(source.get("tool_call_ids") or [])
    return "\n".join(
        [
            "Compact complete.",
            f"- id: {_value(record.get('id') if isinstance(record, dict) else None)}",
            f"- source: messages[{start}:{end}]",
            f"- tool calls: {tool_count}",
        ]
    )


async def handle_model(context: SlashCommandContext, args: list[str]) -> str:
    if args and args[0].lower() == "set":
        return "Model switching is not implemented yet."
    model = _value(getattr(context.session, "model", None))
    return f"Model: {model}\nModel switching will be added in config/model management."


async def handle_login(context: SlashCommandContext, args: list[str]) -> str:
    return "Login/config setup is not implemented yet.\nCreate settings.json under your user .chainpeer directory for now."


async def handle_config(context: SlashCommandContext, args: list[str]) -> str:
    from agent.infrastructure.config import Config

    api_key_state = "set" if Config.OPENAI_API_KEY else "unset"
    reasoning = Config.MODEL_REASONING_EFFORT or "unset"
    settings_state = "found" if Config.SETTINGS_EXISTS else "missing"
    return "\n".join(
        [
            "Config:",
            f"- settings: {Config.SETTINGS_PATH} ({settings_state})",
            f"- apiKey: {api_key_state}",
            f"- baseUrl: {Config.OPENAI_API_BASE}",
            f"- model: {Config.DEFAULT_MODEL}",
            f"- reasoningEffort: {reasoning}",
        ]
    )


async def handle_exit(context: SlashCommandContext, args: list[str]) -> SlashCommandResult:
    return SlashCommandResult("再见！", should_exit=True)


def _value(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _parse_limit(args: list[str], *, default: int, maximum: int) -> int | None:
    if not args:
        return default
    if len(args) != 1:
        return None
    try:
        limit = int(args[0])
    except ValueError:
        return None
    if limit <= 0:
        return None
    return min(limit, maximum)


def _format_session_size(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    messages = _safe_count(value.get("messages"))
    tools = _safe_count(value.get("tool_calls"))
    return f"{messages} msg, {tools} tool"


def _safe_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _truncate(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


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
