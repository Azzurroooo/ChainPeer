"""Runtime event definitions for conversation and tool execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


@dataclass(slots=True)
class RuntimeEvent:
    """Base class for all runtime events."""
    type: str
    ts: str = field(default_factory=lambda: str(time.time()))

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeEvent:
        """Deserialize a dictionary to a RuntimeEvent instance."""
        event_type = data.get("type")
        
        # We need to dispatch to the correct subclass
        for subclass in cls.__subclasses__():
            # Get the default value of 'type' field from the subclass
            if hasattr(subclass, "__dataclass_fields__") and "type" in subclass.__dataclass_fields__:
                type_field = subclass.__dataclass_fields__["type"]
                if type_field.default == event_type:
                    # Filter data to only include valid fields for this subclass
                    valid_keys = {f.name for f in subclass.__dataclass_fields__.values()}
                    filtered_data = {k: v for k, v in data.items() if k in valid_keys}
                    return subclass(**filtered_data)
                    
        # Fallback to base class if no match
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)


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
    """Fired when a tool execution is about to begin.

    `args_preview` is a short, human-readable summary of the tool's arguments
    (e.g. for bash it's the command string; for read_file it's the path).
    Computed by the runtime via render_args_preview() so the CLI can show a
    framework-level "what is the agent about to do" panel without trusting
    the model to narrate it.
    """
    type: Literal["tool_call_started"] = "tool_call_started"
    tool_call_id: str = ""
    tool_name: str = ""
    args_preview: str = ""


@dataclass(slots=True)
class ToolProgressEvent(RuntimeEvent):
    """Fired when a tool produces incremental progress (e.g. streaming stdout)."""
    type: Literal["tool_progress"] = "tool_progress"
    tool_call_id: str = ""
    tool_name: str = ""
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolResultEvent(RuntimeEvent):
    """Fired when a tool execution completes and returns a result.

    `status` is "ok" | "error" parsed from the standardized tool_ok/tool_error
    payload. `summary` is a short human-readable line for the CLI panel
    (e.g. "3 files listed" / "Error: file not found"). `duration_ms` is the
    wall-clock execution time. These fields are framework-computed.
    """
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    tool_name: str = ""
    result: str = ""
    status: Literal["ok", "error", "unknown"] = "unknown"
    summary: str = ""
    duration_ms: int = 0


@dataclass(slots=True)
class TurnStartedEvent(RuntimeEvent):
    """Fired at the very beginning of a turn so the CLI can show 'thinking'.

    The CLI uses this to render an early progress indicator before the first
    assistant delta arrives — addressing the perceived 'frozen' silent gap
    while the model is reasoning.
    """
    type: Literal["turn_started"] = "turn_started"
    user_input_preview: str = ""


@dataclass(slots=True)
class ToolBatchStartedEvent(RuntimeEvent):
    """Fired when the runtime is about to execute a batch of N tool calls."""
    type: Literal["tool_batch_started"] = "tool_batch_started"
    count: int = 0
    tool_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlanSnapshotEvent(RuntimeEvent):
    """Fired after a plan_* tool succeeds with a compact snapshot for the CLI panel.

    This lets the CLI render a live progress panel (todo / done / blocked / current focus)
    as a framework-level UX guarantee. Parsed by the runtime from the plan tool's
    JSON result; the agent does not need to narrate plan state in chat.
    """
    type: Literal["plan_snapshot"] = "plan_snapshot"
    title: str = ""
    goal: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    in_progress_steps: int = 0
    blocked_steps: int = 0
    current_focus: str = ""
    version: int = 0


@dataclass(slots=True)
class DataIntegrityWarningEvent(RuntimeEvent):
    """Fired when a tool result looks like a data-source failure that the
    agent must report rather than fabricate.

    Emitted as a framework-level safety signal so the user sees the issue
    explicitly, and so logs/replay can flag fabrication risk.
    """
    type: Literal["data_integrity_warning"] = "data_integrity_warning"
    tool_name: str = ""
    reason: str = ""
    suggested_action: str = ""


@dataclass(slots=True)
class SkillActivatedEvent(RuntimeEvent):
    """Fired when a skill is selected and injected into the model context."""
    type: Literal["skill_activated"] = "skill_activated"
    skill_name: str = ""
    reason: str = ""
    score: int = 0
    source: str = ""
    path: str = ""


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
