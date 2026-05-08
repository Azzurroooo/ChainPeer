"""Domain models for tasks and jobs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass(slots=True)
class JobRecord:
    """Represents the persisted state of a tool execution job."""
    job_id: str
    session_id: str
    request_id: str
    tool_call_id: str
    tool_name: str
    status: JobStatus = "pending"
    started_at: str | None = None
    ended_at: str | None = None
    output_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def mark_running(self) -> None:
        self.status = "running"
        if not self.started_at:
            self.started_at = str(time.time())
            
    def mark_completed(self) -> None:
        self.status = "completed"
        if not self.ended_at:
            self.ended_at = str(time.time())
            
    def mark_failed(self, error: str = "") -> None:
        self.status = "failed"
        if not self.ended_at:
            self.ended_at = str(time.time())
        self.metadata["error"] = error
            
    def mark_cancelled(self, reason: str = "") -> None:
        self.status = "cancelled"
        if not self.ended_at:
            self.ended_at = str(time.time())
        if reason:
            self.metadata["cancel_reason"] = reason


@dataclass(slots=True)
class ToolExecutionResult:
    """Structured result for synchronous tool execution."""
    status: Literal["ok", "error", "cancelled"]
    result_str: str = ""
    error_msg: str = ""
    error_type: str = ""
    exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


@dataclass(slots=True)
class JobHandle:
    """Runtime handle for a running job."""
    job_id: str
    status: JobStatus
    output_ref: str | None
    
    # We'll attach cancellation and streaming methods at the service level, 
    # but the handle itself holds the identity.
