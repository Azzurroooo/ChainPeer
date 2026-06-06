"""Runtime event renderer for the interactive CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.console import Console

from agent.domain.events import (
    RuntimeEvent,
    SkillActivatedEvent,
    ToolCallStartedEvent,
    ToolProgressEvent,
    ToolRequestedEvent,
    ToolResultEvent,
    TokenStatsUpdatedEvent,
    TurnCancelledEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnStartedEvent,
)
from agent.interfaces.cli.formatting import clip_text, escaped_newlines

from .activity import tool_activity_summary
from .state import ToolDisplayState, TurnDisplayState


class CliStatusRenderer:
    """Render runtime status events without mixing them into assistant text."""

    def __init__(
        self,
        console: Console,
        *,
        debug: bool = False,
        before_print: Callable[[], None] | None = None,
    ) -> None:
        self._console = console
        self._debug = debug
        self._before_print = before_print
        self._state = TurnDisplayState()

    def handle(self, event: RuntimeEvent) -> None:
        """Render a runtime event if it is relevant to CLI status."""
        if isinstance(event, TurnStartedEvent):
            self._handle_turn_started(event)
        elif isinstance(event, SkillActivatedEvent):
            self._handle_skill_activated(event)
        elif isinstance(event, ToolRequestedEvent):
            self._handle_tool_requested(event)
        elif isinstance(event, ToolCallStartedEvent):
            self._handle_tool_started(event)
        elif isinstance(event, ToolProgressEvent):
            self._handle_tool_progress(event)
        elif isinstance(event, ToolResultEvent):
            self._handle_tool_result(event)
        elif isinstance(event, TokenStatsUpdatedEvent):
            self._handle_token_stats(event)
        elif isinstance(event, TurnCompletedEvent):
            self._handle_turn_completed(event)
        elif isinstance(event, TurnFailedEvent):
            self._handle_turn_failed(event)
        elif isinstance(event, TurnCancelledEvent):
            self._handle_turn_cancelled(event)

    def _handle_turn_started(self, event: TurnStartedEvent) -> None:
        self._state = TurnDisplayState(turn_id=event.turn_id)
        if self._debug:
            self._print_debug(
                f"turn started: turn_id={event.turn_id or 'unknown'}, "
                f"user_message_chars={event.user_message_chars}"
            )

    def _handle_skill_activated(self, event: SkillActivatedEvent) -> None:
        skill_name = event.skill_name or "unknown"
        skill_key = skill_name.lower()
        if skill_key in self._state.activated_skills:
            return
        self._state.activated_skills.add(skill_key)
        if self._debug:
            detail = f" reason={event.reason}" if event.reason else ""
            self._print_debug(f"skill activated: {skill_name}{detail}")
            return
        reason = f" ({event.reason})" if event.reason else ""
        self._print_status(f"Skill: {skill_name}{reason}")

    def _handle_tool_requested(self, event: ToolRequestedEvent) -> None:
        state = self._get_tool_state(event.tool_call_id, event.tool_name)
        state.status = "requested"
        state.args_preview = event.args_preview or ""
        if self._debug:
            args = clip_text(escaped_newlines(state.args_preview), 400, strip=False)
            suffix = f" args={args}" if args else ""
            self._print_debug(
                f"tool requested: {state.name} id={state.tool_call_id or 'unknown'}{suffix}"
            )
            return
        self._print_status(f"Running {tool_activity_summary(state.name, state.args_preview)}")
        state.request_rendered = True

    def _handle_tool_started(self, event: ToolCallStartedEvent) -> None:
        state = self._get_tool_state(event.tool_call_id, event.tool_name)
        state.status = "running"
        if self._debug:
            self._print_debug(f"tool started: {state.name} id={state.tool_call_id or 'unknown'}")
            return
        if state.request_rendered:
            return
        self._print_status(f"Running {state.name}")
        state.request_rendered = True

    def _handle_tool_progress(self, event: ToolProgressEvent) -> None:
        message = _progress_message(event.payload)
        if not message:
            return
        state = self._get_tool_state(event.tool_call_id, event.tool_name)
        if state.last_progress == message:
            return
        state.last_progress = message
        if self._debug:
            self._print_debug(
                f"tool progress: {state.name} id={state.tool_call_id or 'unknown'} "
                f"{clip_text(escaped_newlines(message), 300, strip=False)}"
            )
            return
        self._print_status(f"Tool: {state.name} {clip_text(escaped_newlines(message), 120, strip=False)}")

    def _handle_tool_result(self, event: ToolResultEvent) -> None:
        state = self._get_tool_state(event.tool_call_id, event.tool_name)
        state.status = event.status
        state.duration_ms = event.duration_ms
        state.error_type = event.error_type or ""
        duration = _format_duration(event.duration_ms)
        if event.status == "failed":
            error = f" ({state.error_type})" if state.error_type else ""
            self._print_status(f"Tool: {state.name} failed in {duration}{error}", style="red")
            return
        self._print_status(f"Tool: {state.name} completed in {duration}")

    def _handle_turn_completed(self, event: TurnCompletedEvent) -> None:
        completed, failed = self._tool_counts()
        if not self._debug and completed + failed == 0:
            return
        duration = _format_duration(event.duration_ms)
        if failed:
            self._print_status(f"Done in {duration} - tools {completed} completed, {failed} failed")
            return
        self._print_status(f"Done in {duration} - tools {completed} completed")

    def _handle_turn_failed(self, event: TurnFailedEvent) -> None:
        message = event.error or "unknown"
        if self._debug and event.error_type:
            message = f"{message} ({event.error_type})"
        self._print_status(f"[Error] Turn failed: {message}", style="red")

    def _handle_turn_cancelled(self, event: TurnCancelledEvent) -> None:
        self._print_status(f"[Cancelled] Turn cancelled: {event.reason or 'unknown'}", style="yellow")

    def _handle_token_stats(self, event: TokenStatsUpdatedEvent) -> None:
        stats = event.stats if isinstance(event.stats, dict) else {}
        input_tokens = int(stats.get("input_tokens") or 0)
        effective_window = int(stats.get("effective_context_window_tokens") or 0)
        cached = int(stats.get("cached_input_tokens") or 0)
        output = int(stats.get("output_tokens") or 0)
        context_pct = _format_percent(stats.get("context_usage_percent"))
        cache_pct = _format_percent(stats.get("cache_hit_rate"))
        limit_text = f" / {_format_count(effective_window)}" if effective_window > 0 else ""
        self._print_status(
            "Tokens: "
            f"input {_format_count(input_tokens)}{limit_text} ({context_pct}), "
            f"cached {_format_count(cached)} ({cache_pct}), "
            f"output {_format_count(output)}"
        )

    def _get_tool_state(self, tool_call_id: str, tool_name: str) -> ToolDisplayState:
        key = tool_call_id or f"tool:{tool_name or 'unknown'}"
        state = self._state.tools.get(key)
        if state is None:
            state = ToolDisplayState(tool_call_id=tool_call_id, name=tool_name or "unknown")
            self._state.tools[key] = state
        elif tool_name:
            state.name = tool_name
        return state

    def _tool_counts(self) -> tuple[int, int]:
        completed = sum(1 for item in self._state.tools.values() if item.status == "completed")
        failed = sum(1 for item in self._state.tools.values() if item.status == "failed")
        return completed, failed

    def _print_debug(self, message: str) -> None:
        self._print_status(f"[debug] {message}", style="dim italic")

    def _print_status(self, message: str, *, style: str = "dim italic") -> None:
        if self._before_print:
            self._before_print()
        self._console.print(message, style=style, highlight=False, markup=False)


def _format_count(value: Any) -> str:
    if not isinstance(value, int | float):
        return str(value)
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    return str(int(value))


def _format_duration(duration_ms: int | None) -> str:
    if not duration_ms:
        return "0ms"
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms / 1000:.2f}s"


def _format_percent(value: Any) -> str:
    if not isinstance(value, int | float):
        return "0.0%"
    return f"{value * 100:.1f}%"


def _progress_message(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("message", "status", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
