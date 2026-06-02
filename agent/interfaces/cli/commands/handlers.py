"""Handlers for CLI slash commands."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Callable

from .router import SlashCommandContext, SlashCommandInfo, SlashCommandResult


COMMAND_INFOS = (
    SlashCommandInfo("help", "Show commands", "/help [command]"),
    SlashCommandInfo("status", "Show session status", "/status"),
    SlashCommandInfo("doctor", "Run local setup diagnostics", "/doctor"),
    SlashCommandInfo("sessions", "List recent sessions", "/sessions [limit]"),
    SlashCommandInfo("skill", "List skills", "/skill [list]"),
    SlashCommandInfo("plan", "Show active plan summary", "/plan"),
    SlashCommandInfo("compact", "Compact current session context", "/compact"),
    SlashCommandInfo("model", "Show or change the active model", "/model | /model set <model>"),
    SlashCommandInfo("clear", "Clear terminal output", "/clear"),
    SlashCommandInfo("draft", "Show saved input draft", "/draft"),
    SlashCommandInfo("login", "Show login setup guidance", "/login"),
    SlashCommandInfo("config", "Show config guidance", "/config"),
    SlashCommandInfo("exit", "Exit CLI", "/exit", aliases=("quit",)),
)


def default_command_infos() -> list[SlashCommandInfo]:
    return list(COMMAND_INFOS)


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
        "clear": handle_clear,
        "draft": handle_draft,
        "login": handle_login,
        "config": handle_config,
        "exit": handle_exit,
        "quit": handle_exit,
    }


async def handle_help(context: SlashCommandContext, args: list[str]) -> str:
    if len(args) > 1:
        return "Usage: /help [command]"
    if args:
        return _render_command_help(COMMAND_INFOS, args[0])
    return _render_help(COMMAND_INFOS)


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
                "Last sampling:",
                f"- input: {_format_count(input_tokens)}{limit} ({_format_percent(latest_usage.get('context_usage_percent'))})",
                f"- cached: {_format_count(cached_tokens)} ({_format_percent(latest_usage.get('cache_hit_rate'))})",
                f"- output: {_format_count(output_tokens)}",
            ]
        )
    recent_tools = await _recent_tool_summaries(session)
    if recent_tools:
        lines.append("Recent tools:")
        lines.extend(f"- {item}" for item in recent_tools)
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
    from agent.infrastructure.config import Config

    if not args:
        active = _value(getattr(context.session, "model", None))
        configured = _value(Config.DEFAULT_MODEL)
        if active == configured:
            return f"Model: {active}"
        return f"Model:\n- active: {active}\n- default: {configured}"

    if len(args) != 2 or args[0].lower() != "set":
        return "Usage: /model or /model set <model>"

    model = _normalize_model_name(args[1])
    if model is None:
        return "Usage: /model set <model>"

    previous = _value(Config.DEFAULT_MODEL)
    try:
        Config.set_model(model)
        active_updated = await _set_active_model(context, model)
    except Exception as exc:
        return f"Command failed: {exc}"

    lines = [
        "Model updated.",
        f"- previous default: {previous}",
        f"- new default: {Config.DEFAULT_MODEL}",
    ]
    if active_updated:
        lines.append("- active session: updated")
    else:
        lines.append("- active session: unchanged; start a new session to use this model")
    return "\n".join(lines)


async def handle_clear(context: SlashCommandContext, args: list[str]) -> SlashCommandResult:
    if args:
        return SlashCommandResult("Usage: /clear")
    return SlashCommandResult(clear_screen=True)


async def handle_draft(context: SlashCommandContext, args: list[str]) -> str:
    if args:
        return "Usage: /draft"
    path = _draft_path(context.session)
    if path is None or not path.exists():
        return "No saved input draft."
    try:
        draft = path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        return f"Command failed: {exc}"
    if not draft:
        return "No saved input draft."
    return f"Saved input draft: {path}\n\n{draft}"


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


def _render_help(command_infos: tuple[SlashCommandInfo, ...]) -> str:
    command_width = max(len(info.name) for info in command_infos) + 3
    lines = ["Available commands:"]
    for info in command_infos:
        aliases = f" (alias: {', '.join('/' + alias for alias in info.aliases)})" if info.aliases else ""
        lines.append(f"/{info.name:<{command_width}}{info.description}{aliases}")
    return "\n".join(lines)


def _render_command_help(command_infos: tuple[SlashCommandInfo, ...], command: str) -> str:
    name = command.strip().lstrip("/").lower()
    info = _find_command_info(command_infos, name)
    if info is None:
        return f"Unknown command: /{name}\nRun /help to see available commands."
    lines = [
        f"/{info.name}",
        f"- {info.description}",
        f"- usage: {info.usage or '/' + info.name}",
    ]
    if info.aliases:
        lines.append(f"- aliases: {', '.join('/' + alias for alias in info.aliases)}")
    return "\n".join(lines)


def _find_command_info(command_infos: tuple[SlashCommandInfo, ...], name: str) -> SlashCommandInfo | None:
    for info in command_infos:
        if info.name == name or name in info.aliases:
            return info
    return None


def _git_status_line() -> str:
    try:
        from agent.interfaces.cli.ui import GitPromptStatusProvider

        status = GitPromptStatusProvider(ttl_seconds=0).current()
    except Exception:
        return ""
    if status is None:
        return ""
    marker = "*" if status.dirty else ""
    return f"- Git: {status.branch}{marker}"


def _draft_path(session) -> Path | None:
    base = _session_base_path(session)
    return base / "input_draft.txt" if base else None


def _session_base_path(session) -> Path | None:
    paths = getattr(session, "_session_paths", None)
    if isinstance(paths, dict) and paths.get("base"):
        return Path(str(paths["base"]))
    root = getattr(session, "_session_root", None)
    session_id = getattr(session, "session_id", None)
    if root and session_id:
        return Path(str(root)) / str(session_id)
    return None


def _value(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


async def _set_active_model(context: SlashCommandContext, model: str) -> bool:
    set_model = getattr(context.runtime, "set_model", None)
    if callable(set_model):
        result = set_model(model)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            return bool(result.get("runtime") or result.get("session"))
        if isinstance(result, bool):
            return result
        return True

    update_model = getattr(context.session, "update_model", None)
    if callable(update_model):
        result = update_model(model)
        if inspect.isawaitable(result):
            await result
        return True
    return False


def _normalize_model_name(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or any(character.isspace() for character in text):
        return None
    if len(text) > 128:
        return None
    return text


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


async def _recent_tool_summaries(session, *, limit: int = 3) -> list[str]:
    get_records = getattr(session, "get_tool_records", None)
    if not callable(get_records):
        return []
    try:
        records = await get_records(limit=limit)
    except TypeError:
        records = await get_records()
    except Exception:
        return []
    if not isinstance(records, list):
        return []
    return [_tool_summary(record) for record in records[-limit:] if isinstance(record, dict)]


def _tool_summary(record: dict) -> str:
    name = _value(record.get("name"))
    status = _tool_status(record)
    ended = _short_timestamp(record.get("ts_end"))
    detail = _tool_detail(record)
    suffix = f" | {detail}" if detail else ""
    return f"{name} {status} {ended}{suffix}".strip()


def _tool_status(record: dict) -> str:
    ok = record.get("ok")
    if ok is True:
        return "ok"
    if ok is False:
        error_type = _value(record.get("error_type"))
        return f"failed ({error_type})" if error_type != "unknown" else "failed"
    return "done"


def _tool_detail(record: dict) -> str:
    meta = record.get("meta")
    if not isinstance(meta, dict):
        return ""
    if "exit_code" in meta:
        return f"exit {meta.get('exit_code')}"
    if "stdout_size" in meta:
        return f"stdout {_format_count(meta.get('stdout_size'))} chars"
    return ""


def _short_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if "T" in text:
        return text.split("T", 1)[1].split(".", 1)[0]
    return text or "unknown"


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
