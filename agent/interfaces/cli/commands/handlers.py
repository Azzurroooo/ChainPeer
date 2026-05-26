"""Handlers for CLI slash commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .router import SlashCommandContext, SlashCommandResult


def default_handlers() -> dict[str, Callable]:
    return {
        "help": handle_help,
        "status": handle_status,
        "skill": handle_skill,
        "plan": handle_plan,
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
            "/skill     List skills",
            "/plan      Show active plan summary",
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
    return "\n".join(
        [
            "Status:",
            f"- Session: {_value(getattr(session, 'session_id', None))}",
            f"- Model: {_value(getattr(session, 'model', None))}",
            f"- Debug: {str(bool(context.debug)).lower()}",
            f"- Messages: {message_count}",
        ]
    )


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


async def handle_model(context: SlashCommandContext, args: list[str]) -> str:
    if args and args[0].lower() == "set":
        return "Model switching is not implemented yet."
    model = _value(getattr(context.session, "model", None))
    return f"Model: {model}\nModel switching will be added in config/model management."


async def handle_login(context: SlashCommandContext, args: list[str]) -> str:
    return "Login/config setup is not implemented yet.\nSet OPENAI_API_KEY in your environment or .env for now."


async def handle_config(context: SlashCommandContext, args: list[str]) -> str:
    api_key_state = "set" if os.getenv("OPENAI_API_KEY") else "unset"
    api_base = os.getenv("OPENAI_API_BASE") or "unset"
    return "\n".join(
        [
            "Config:",
            f"- OPENAI_API_KEY: {api_key_state}",
            f"- OPENAI_API_BASE: {api_base}",
            "Persistent config commands will be added later.",
        ]
    )


async def handle_exit(context: SlashCommandContext, args: list[str]) -> SlashCommandResult:
    return SlashCommandResult("再见！", should_exit=True)


def _value(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"
