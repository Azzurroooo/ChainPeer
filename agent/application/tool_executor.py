"""Application-level safe tool execution service."""

from __future__ import annotations

import traceback
import asyncio
from typing import AsyncIterator

from agent.application.ports import ToolRegistry
from agent.application.services.job_service import JobService
from agent.domain import looks_like_tool_payload, tool_error, tool_ok
from agent.domain.jobs import ToolExecutionResult, JobHandle, JobStatus
from agent.domain.events import RuntimeEvent, ToolProgressEvent, ToolResultEvent


class ToolExecutor:
    """Runs tool calls with standardized error handling and job semantics."""

    def __init__(self, registry: ToolRegistry, job_service: JobService | None = None):
        self._registry = registry
        self._job_service = job_service

    def execute(self, name: str, args: dict, raw_args: str | None = None) -> str:
        """Legacy synchronous execution returning a string payload."""
        result = self.execute_sync(name, args, raw_args)
        if result.status == "ok":
            if isinstance(result.result_str, str) and looks_like_tool_payload(result.result_str):
                return result.result_str
            return tool_ok(name, result.result_str)
        else:
            return tool_error(name, result.error_msg, result.error_type, meta=result.metadata)

    def execute_sync(self, name: str, args: dict, raw_args: str | None = None) -> ToolExecutionResult:
        """Synchronous execution returning a structured ToolExecutionResult."""
        if not self._registry.has(name):
            return ToolExecutionResult(
                status="error",
                error_msg=f"Unknown tool: {name}",
                error_type="ToolNotFound"
            )
        try:
            result = self._registry.call(name, args)
            return ToolExecutionResult(
                status="ok",
                result_str=result if isinstance(result, str) else str(result)
            )
        except TypeError as exc:
            meta = {"raw_args": (raw_args or "")[:2000]} if raw_args else {}
            return ToolExecutionResult(
                status="error",
                error_msg=str(exc),
                error_type=type(exc).__name__,
                metadata=meta
            )
        except Exception as exc:
            meta = {"traceback": traceback.format_exc()[-4000:]}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return ToolExecutionResult(
                status="error",
                error_msg=str(exc),
                error_type=type(exc).__name__,
                metadata=meta
            )

    def start_job(
        self,
        session_id: str,
        request_id: str,
        tool_call_id: str,
        name: str,
        args: dict,
        raw_args: str | None = None
    ) -> JobHandle:
        """Start a tool execution job."""
        if not self._job_service:
            raise RuntimeError("JobService is required to start a job")
            
        handle = self._job_service.create_job(
            session_id=session_id,
            request_id=request_id,
            tool_call_id=tool_call_id,
            tool_name=name,
            metadata={"args": args, "raw_args": raw_args}
        )
        
        # For Phase 1, we simulate job execution synchronously in start_job 
        # or we just run it and update the status immediately for short tasks.
        # For bash, Phase 2 will introduce real background running.
        # Here we just run it synchronously to bridge the gap, but update job store.
        self._job_service.update_status(handle.job_id, "running")
        
        result = self.execute_sync(name, args, raw_args)
        
        if result.status == "ok":
            self._job_service.append_output(handle.job_id, result.result_str)
            self._job_service.update_status(handle.job_id, "completed")
        else:
            self._job_service.append_output(handle.job_id, f"Error: {result.error_msg}")
            self._job_service.update_status(handle.job_id, "failed", error=result.error_msg)
            
        return handle

    async def stream_job_events(self, job_id: str) -> AsyncIterator[RuntimeEvent]:
        """Stream events for a running job."""
        if not self._job_service:
            raise RuntimeError("JobService is required to stream job events")
            
        job = self._job_service.get_job(job_id)
        if not job:
            return
            
        # In Phase 1, since jobs are actually executed synchronously during start_job,
        # by the time we stream events, the job is likely already completed.
        # We just yield the final result event.
        # In Phase 2, this will poll or await real-time events.
        content, _ = self._job_service.read_output(job_id)
        
        if content:
            yield ToolProgressEvent(
                tool_call_id=job.tool_call_id,
                tool_name=job.tool_name,
                payload={"stdout": content}
            )
            
        yield ToolResultEvent(
            tool_call_id=job.tool_call_id,
            tool_name=job.tool_name,
            result=content
        )
