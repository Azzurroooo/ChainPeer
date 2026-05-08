"""Handles tool call execution and result formatting."""

from __future__ import annotations

from typing import Callable
import asyncio

from agent.application.ports import SessionStore
from agent.domain import ParsedToolCall, parse_tool_args, tool_error
from agent.domain.events import RuntimeEvent, ToolCallStartedEvent, ToolResultEvent


class ToolCallProcessor:
    """Executes parsed tool calls and persists results."""

    def __init__(self, tool_executor):
        self._tool_executor = tool_executor

    def execute_parsed_tool_call(self, call: ParsedToolCall) -> str:
        """Execute a single tool call without persisting (e.g. for single queries)."""
        parsed_args, parse_error = parse_tool_args(call.raw_args)
        if parse_error:
            return tool_error(
                call.name,
                f"Invalid tool arguments JSON: {parse_error}",
                "ToolArgsJSONError",
                meta={"raw_args": call.raw_args[:2000]},
            )
        return self._tool_executor.execute(call.name, parsed_args, raw_args=call.raw_args)

    def execute_tool_calls(
        self,
        session: SessionStore,
        tool_calls: list[ParsedToolCall],
        on_debug: Callable[[str], None] | None = None,
        on_event: Callable[[RuntimeEvent], None] | None = None,
    ) -> None:
        """Execute multiple tool calls and persist the results to the session."""
        request_id = session.now_iso() # using timestamp as a pseudo request_id for now
        
        for call in tool_calls:
            if on_debug:
                on_debug(f"Tool Call: {call.name}({call.raw_args})")
                
            if on_event:
                on_event(ToolCallStartedEvent(tool_call_id=call.call_id, tool_name=call.name))

            parsed_args, parse_error = parse_tool_args(call.raw_args)
            ts_start = session.now_iso()
            
            if parse_error:
                tool_result_str = tool_error(
                    call.name,
                    f"Invalid tool arguments JSON: {parse_error}",
                    "ToolArgsJSONError",
                    meta={"raw_args": call.raw_args[:2000]},
                )
                if on_event:
                    on_event(ToolResultEvent(tool_call_id=call.call_id, tool_name=call.name, result=tool_result_str))
            else:
                # Use the new Job-based execution
                try:
                    handle = self._tool_executor.start_job(
                        session_id=session.session_id or "default",
                        request_id=request_id,
                        tool_call_id=call.call_id,
                        name=call.name,
                        args=parsed_args,
                        raw_args=call.raw_args
                    )
                    
                    # Consume events synchronously for Phase 1
                    async def consume_events():
                        async for event in self._tool_executor.stream_job_events(handle.job_id):
                            if on_event:
                                on_event(event)
                                
                    asyncio.run(consume_events())
                    
                    # Get final result
                    # Since stream_job_events yields ToolResultEvent at the end, 
                    # we can read the output from job service or just read it here.
                    content, _ = self._tool_executor._job_service.read_output(handle.job_id)
                    job = self._tool_executor._job_service.get_job(handle.job_id)
                    if job and job.status == "failed":
                        tool_result_str = tool_error(call.name, job.metadata.get("error", "Unknown error"), "JobFailed")
                    else:
                        from agent.domain import looks_like_tool_payload, tool_ok
                        if looks_like_tool_payload(content):
                            tool_result_str = content
                        else:
                            tool_result_str = tool_ok(call.name, content)
                            
                except Exception as exc:
                    # Fallback to legacy execution if JobService is not configured
                    tool_result_str = self._tool_executor.execute(call.name, parsed_args, raw_args=call.raw_args)
                    if on_event:
                        on_event(ToolResultEvent(tool_call_id=call.call_id, tool_name=call.name, result=tool_result_str))

            ts_end = session.now_iso()

            session.persist_tool_call(
                call.call_id,
                call.name,
                parsed_args,
                call.raw_args,
                ts_start,
                ts_end,
                tool_result_str,
            )
            session.persist_message("tool", "", tool_call_id=call.call_id, tool_name=call.name)
            if on_debug:
                on_debug(f"Tool Result: {tool_result_str}")
