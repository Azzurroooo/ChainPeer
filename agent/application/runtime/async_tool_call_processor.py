"""Asynchronous tool scheduler and execution layer."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.services.job_service import JobService
from agent.domain import ParsedToolCall, parse_tool_args, tool_error, tool_ok
from agent.domain.events import RuntimeEvent, ToolCallStartedEvent, ToolResultEvent, ToolProgressEvent
from agent.application.tool_executor import ToolExecutor
from agent.application.runtime.cancellation import CancellationToken


class AsyncToolCallProcessor:
    """
    Executes parsed tool calls asynchronously, enforcing concurrency rules
    and yielding an event stream. Replaces the legacy ToolCallProcessor.
    """

    def __init__(self, tool_executor: ToolExecutor, job_service: JobService):
        self._tool_executor = tool_executor
        self._job_service = job_service

    async def execute(
        self,
        session: AsyncSessionStore,
        tool_calls: list[ParsedToolCall],
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """
        Execute multiple tool calls asynchronously.
        Async tools (like bash) are awaited directly; sync tools run in a thread.
        """
        request_id = session.now_iso()

        for call in tool_calls:
            if cancellation_token and cancellation_token.is_cancelled:
                break

            yield ToolCallStartedEvent(tool_call_id=call.call_id, tool_name=call.name)

            parsed_args, parse_error = parse_tool_args(call.raw_args)
            ts_start = session.now_iso()

            if parse_error:
                tool_result_str = tool_error(
                    call.name,
                    f"Invalid tool arguments JSON: {parse_error}",
                    "ToolArgsJSONError",
                    meta={"raw_args": call.raw_args[:2000]},
                )
                yield ToolResultEvent(tool_call_id=call.call_id, tool_name=call.name, result=tool_result_str)
            else:
                try:
                    handle = await asyncio.to_thread(
                        self._job_service.create_job,
                        session_id=session.session_id or "default",
                        request_id=request_id,
                        tool_call_id=call.call_id,
                        tool_name=call.name,
                        metadata={"args": parsed_args, "raw_args": call.raw_args}
                    )
                    await asyncio.to_thread(self._job_service.update_status, handle.job_id, "running")

                    if self._tool_executor.is_async_tool(call.name):
                        # Inject _cancellation_token for tools that accept it (e.g. bash)
                        if call.name == "bash":
                            parsed_args = {**parsed_args, "_cancellation_token": cancellation_token}
                        result = await self._tool_executor.execute_async(call.name, parsed_args, call.raw_args)
                    else:
                        def _sync_run():
                            return self._tool_executor.execute_sync(call.name, parsed_args, call.raw_args)
                        result = await asyncio.to_thread(_sync_run)

                    if result.status == "ok":
                        await asyncio.to_thread(self._job_service.append_output, handle.job_id, result.result_str)
                        await asyncio.to_thread(self._job_service.update_status, handle.job_id, "completed")
                    else:
                        await asyncio.to_thread(self._job_service.append_output, handle.job_id, f"Error: {result.error_msg}")
                        await asyncio.to_thread(self._job_service.update_status, handle.job_id, "failed", error=result.error_msg)

                    content, _ = await asyncio.to_thread(self._job_service.read_output, handle.job_id)
                    job = await asyncio.to_thread(self._job_service.get_job, handle.job_id)

                    if job and job.status == "failed":
                        tool_result_str = tool_error(call.name, job.metadata.get("error", "Unknown error"), "JobFailed")
                    else:
                        from agent.domain import looks_like_tool_payload
                        if looks_like_tool_payload(content):
                            tool_result_str = content
                        else:
                            tool_result_str = tool_ok(call.name, content)

                except Exception as exc:
                    tool_result_str = tool_error(call.name, str(exc), type(exc).__name__)

                yield ToolResultEvent(tool_call_id=call.call_id, tool_name=call.name, result=tool_result_str)

            ts_end = session.now_iso()

            await session.persist_tool_call(
                call.call_id,
                call.name,
                parsed_args,
                call.raw_args,
                ts_start,
                ts_end,
                tool_result_str,
            )
            await session.persist_message("tool", "", tool_call_id=call.call_id, tool_name=call.name)
