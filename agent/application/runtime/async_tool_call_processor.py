"""Asynchronous tool scheduler and execution layer."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.domain import ParsedToolCall, looks_like_tool_payload, parse_tool_args, tool_error, tool_ok
from agent.domain.events import RuntimeEvent, ToolCallStartedEvent, ToolResultEvent, event_meta
from agent.application.tool_executor import ToolExecutor
from agent.application.runtime.cancellation import CancellationToken
from agent.application.services.tool_result_normalizer import ToolResultNormalizer


class AsyncToolCallProcessor:
    """
    Executes parsed tool calls asynchronously, enforcing concurrency rules
    and yielding an event stream. Replaces the legacy ToolCallProcessor.
    """

    def __init__(self, tool_executor: ToolExecutor, tool_result_normalizer: ToolResultNormalizer | None = None):
        self._tool_executor = tool_executor
        self._tool_result_normalizer = tool_result_normalizer or ToolResultNormalizer()

    async def execute(
        self,
        session: AsyncSessionStore,
        tool_calls: list[ParsedToolCall],
        cancellation_token: CancellationToken | None = None,
        turn_id: str = "",
    ) -> AsyncIterator[RuntimeEvent]:
        """
        Execute multiple tool calls asynchronously.
        Async tools (like bash) are awaited directly; sync tools run in a thread.
        """
        for call in tool_calls:
            if cancellation_token and cancellation_token.is_cancelled:
                break

            started_at = time.perf_counter()
            parsed_args, parse_error = parse_tool_args(call.raw_args)
            persisted_args = dict(parsed_args)
            ts_start = session.now_iso()
            event_status = "completed"
            error_type = ""

            if parse_error:
                event_status = "failed"
                error_type = "ToolArgsJSONError"
                tool_result_str = tool_error(
                    call.name,
                    f"Invalid tool arguments JSON: {parse_error}",
                    error_type,
                    meta={"raw_args": call.raw_args[:2000]},
                )
            else:
                yield ToolCallStartedEvent(
                    **event_meta(session, turn_id),
                    tool_call_id=call.call_id,
                    tool_name=call.name,
                )
                try:
                    if self._tool_executor.is_async_tool(call.name):
                        # Inject _cancellation_token for tools that accept it (e.g. bash)
                        execution_args = parsed_args
                        if call.name == "bash":
                            execution_args = {**parsed_args, "_cancellation_token": cancellation_token}
                        result = await self._tool_executor.execute_async(call.name, execution_args, call.raw_args)
                    else:
                        def _sync_run():
                            return self._tool_executor.execute_sync(call.name, parsed_args, call.raw_args)
                        result = await asyncio.to_thread(_sync_run)

                    if result.status == "ok":
                        tool_result_str = result.result_str
                        if not looks_like_tool_payload(tool_result_str):
                            tool_result_str = tool_ok(call.name, tool_result_str)
                    else:
                        event_status = "failed"
                        error_type = result.error_type or "ToolExecutionError"
                        tool_result_str = tool_error(call.name, result.error_msg, error_type)

                except Exception as exc:
                    event_status = "failed"
                    error_type = type(exc).__name__
                    tool_result_str = tool_error(call.name, str(exc), error_type)

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield ToolResultEvent(
                **event_meta(session, turn_id),
                tool_call_id=call.call_id,
                tool_name=call.name,
                status=event_status,
                result=tool_result_str,
                error_type=error_type,
                duration_ms=duration_ms,
            )

            ts_end = session.now_iso()
            normalized_result = self._tool_result_normalizer.normalize(tool_result_str)

            await session.persist_tool_call(
                call.call_id,
                call.name,
                persisted_args,
                call.raw_args,
                ts_start,
                ts_end,
                tool_result_str,
                model_content=normalized_result.model_content,
                model_content_format=normalized_result.model_content_format,
                model_content_policy=normalized_result.model_content_policy,
                artifact_ref=normalized_result.artifact_ref,
            )
            await session.persist_message("tool", "", tool_call_id=call.call_id, tool_name=call.name)
