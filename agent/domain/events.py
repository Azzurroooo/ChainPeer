"""Runtime event definitions for conversation and tool execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class RuntimeEvent:
    """Base class for all runtime events."""
    type: str
    ts: str = field(default_factory=lambda: str(time.time()))


@dataclass(slots=True)
class AssistantDeltaEvent(RuntimeEvent):
    """Fired when a new chunk of text is received from the assistant."""
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str = ""


@dataclass(slots=True)
class AssistantMessageCompletedEvent(RuntimeEvent):
    """Fired when the assistant finishes generating a message."""
    type: Literal["assistant_message_completed"] = "assistant_message_completed"
    content: str = ""


@dataclass(slots=True)
class ToolCallStartedEvent(RuntimeEvent):
    """Fired when a tool execution is about to begin."""
    type: Literal["tool_call_started"] = "tool_call_started"
    tool_call_id: str = ""
    tool_name: str = ""


@dataclass(slots=True)
class ToolProgressEvent(RuntimeEvent):
    """Fired when a tool produces incremental progress (e.g. streaming stdout)."""
    type: Literal["tool_progress"] = "tool_progress"
    tool_call_id: str = ""
    tool_name: str = ""
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolResultEvent(RuntimeEvent):
    """Fired when a tool execution completes and returns a result."""
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    tool_name: str = ""
    result: str = ""


@dataclass(slots=True)
class TurnCompletedEvent(RuntimeEvent):
    """Fired when an entire turn (including all tool executions and LLM generation) completes successfully."""
    type: Literal["turn_completed"] = "turn_completed"


@dataclass(slots=True)
class TurnFailedEvent(RuntimeEvent):
    """Fired when a turn fails due to an error."""
    type: Literal["turn_failed"] = "turn_failed"
    error: str = ""
    error_type: str = ""


@dataclass(slots=True)
class TurnCancelledEvent(RuntimeEvent):
    """Fired when a turn is cancelled (e.g. via CancellationToken)."""
    type: Literal["turn_cancelled"] = "turn_cancelled"
    reason: str = ""
