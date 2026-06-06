"""Handlers for CLI slash commands."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Callable

from agent.interfaces.cli.formatting import clip_text, display_value, nonnegative_int, single_line

from .help_view import render_command_help, render_help
from .router import SlashCommandContext, SlashCommandInfo, SlashCommandResult
from .status_view import render_status


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
    SlashCommandInfo("draft", "Show, reuse, or clear saved input draft", "/draft | /draft use | /draft clear"),
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
        return render_command_help(COMMAND_INFOS, args[0])
    return render_help(COMMAND_INFOS)


async def handle_status(context: SlashCommandContext, args: list[str]) -> str:
    return await render_status(context)


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
        session_id = display_value(item.get("id"))
        marker = " (current)" if current_id and session_id == current_id else ""
        updated = display_value(item.get("updated_at"))
        title = clip_text(display_value(item.get("title")), 40)
        size = _format_session_size(item.get("size"))
        preview = clip_text(single_line(item.get("preview")), 56)
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
            f"- id: {display_value(record.get('id') if isinstance(record, dict) else None)}",
            f"- source: messages[{start}:{end}]",
            f"- tool calls: {tool_count}",
        ]
    )


async def handle_model(context: SlashCommandContext, args: list[str]) -> str:
    from agent.infrastructure.config import Config

    if not args:
        active = display_value(getattr(context.session, "model", None))
        configured = display_value(Config.DEFAULT_MODEL)
        if active == configured:
            return f"Model: {active}"
        return f"Model:\n- active: {active}\n- default: {configured}"

    if len(args) != 2 or args[0].lower() != "set":
        return "Usage: /model or /model set <model>"

    model = _normalize_model_name(args[1])
    if model is None:
        return "Usage: /model set <model>"

    previous = display_value(Config.DEFAULT_MODEL)
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


async def handle_draft(context: SlashCommandContext, args: list[str]) -> str | SlashCommandResult:
    if len(args) > 1 or (args and args[0].lower() not in {"use", "clear"}):
        return "Usage: /draft, /draft use, or /draft clear"
    path = _draft_path(context.session)
    if args and args[0].lower() == "clear":
        return _clear_draft(path)
    if args and args[0].lower() == "use":
        draft = _read_draft(path)
        if draft is None:
            return "No saved input draft."
        return SlashCommandResult("Draft loaded into the next prompt.", input_prefill=draft)
    if path is None or not path.exists():
        return "No saved input draft."
    draft = _read_draft(path)
    if draft is None:
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


def _draft_path(session) -> Path | None:
    base = _session_base_path(session)
    return base / "input_draft.txt" if base else None


def _clear_draft(path: Path | None) -> str:
    if path is None or not path.exists():
        return "No saved input draft."
    try:
        path.unlink()
    except Exception as exc:
        return f"Command failed: {exc}"
    return "Saved input draft cleared."


def _read_draft(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    try:
        draft = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return draft or None


def _session_base_path(session) -> Path | None:
    paths = getattr(session, "_session_paths", None)
    if isinstance(paths, dict) and paths.get("base"):
        return Path(str(paths["base"]))
    root = getattr(session, "_session_root", None)
    session_id = getattr(session, "session_id", None)
    if root and session_id:
        return Path(str(root)) / str(session_id)
    return None


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
    messages = nonnegative_int(value.get("messages"))
    tools = nonnegative_int(value.get("tool_calls"))
    return f"{messages} msg, {tools} tool"
