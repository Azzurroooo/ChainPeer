"""Lightweight slash command router."""

from __future__ import annotations

import inspect
import shlex
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class SlashCommandContext:
    runtime: Any
    session: Any
    debug: bool = False


@dataclass(slots=True)
class SlashCommandResult:
    text: str = ""
    should_exit: bool = False


Handler = Callable[[SlashCommandContext, list[str]], str | SlashCommandResult | Awaitable[str | SlashCommandResult]]


class SlashCommandRouter:
    """Parse and dispatch CLI slash commands."""

    def __init__(self):
        from .handlers import default_handlers

        self._handlers = default_handlers()

    async def execute(self, raw_input: str, context: SlashCommandContext) -> SlashCommandResult:
        try:
            name, args = self._parse(raw_input)
            handler = self._handlers.get(name)
            if not handler:
                return SlashCommandResult(f"Unknown command: /{name}\nRun /help to see available commands.")
            result = handler(context, args)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, SlashCommandResult) else SlashCommandResult(str(result or ""))
        except ValueError as exc:
            return SlashCommandResult(f"Command failed: {exc}")
        except Exception as exc:
            return SlashCommandResult(f"Command failed: {exc}")

    def _parse(self, raw_input: str) -> tuple[str, list[str]]:
        text = raw_input.strip()
        if not text.startswith("/"):
            raise ValueError("Slash command must start with '/'.")
        try:
            parts = shlex.split(text[1:])
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if not parts:
            raise ValueError("Missing command name.")
        return parts[0].lower(), parts[1:]
