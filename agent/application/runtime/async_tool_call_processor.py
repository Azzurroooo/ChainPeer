"""Asynchronous tool scheduler and execution layer."""

from __future__ import annotations

import asyncio
import json
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
        self._empty_bash_output_counts_by_turn: dict[str, dict[str, int]] = {}

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
        empty_bash_output_counts = self._counts_for_turn(turn_id)
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
                blocked_poll = self._empty_bash_output_pre_guard(call.name, parsed_args, empty_bash_output_counts)
                if blocked_poll:
                    event_status = "failed"
                    error_type = "RepeatedEmptyPoll"
                    tool_result_str = blocked_poll
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
                            self._record_bash_output_observation(
                                call.name,
                                tool_result_str,
                                empty_bash_output_counts,
                            )
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

    def _counts_for_turn(self, turn_id: str) -> dict[str, int]:
        if not turn_id:
            return {}
        key = turn_id or "__default__"
        if len(self._empty_bash_output_counts_by_turn) > 32:
            self._empty_bash_output_counts_by_turn.clear()
        return self._empty_bash_output_counts_by_turn.setdefault(key, {})

    def _empty_bash_output_pre_guard(
        self,
        tool_name: str,
        parsed_args: dict,
        counts: dict[str, int],
    ) -> str | None:
        if tool_name != "bash_output":
            return None
        bg_id = str(parsed_args.get("bg_id") or "")
        if not bg_id or counts.get(bg_id, 0) < 3:
            return None
        counts[bg_id] = counts.get(bg_id, 0) + 1
        return self._repeated_empty_poll_error(bg_id, counts[bg_id])

    def _record_bash_output_observation(
        self,
        tool_name: str,
        tool_result_str: str,
        counts: dict[str, int],
    ) -> None:
        if tool_name != "bash_output":
            return
        try:
            payload = json.loads(tool_result_str)
        except Exception:
            return
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        bg_id = str(data.get("bg_id") or "")
        if not bg_id:
            return
        empty_running = (
            data.get("status") == "running"
            and data.get("no_new_output") is True
            and not data.get("stdout")
            and not data.get("stderr")
        )
        if not empty_running:
            counts[bg_id] = 0
            return
        counts[bg_id] = counts.get(bg_id, 0) + 1

    def _repeated_empty_poll_error(self, bg_id: str, count: int) -> str:
        return tool_error(
            "bash_output",
            f"Repeated empty bash_output polling for {bg_id}. Wait longer before checking again, or continue independent work.",
            "RepeatedEmptyPoll",
            meta={
                "bg_id": bg_id,
                "empty_observation_count": count,
                "suggested_next_wait_ms": self._suggested_wait_ms_for_empty_count(count),
            },
        )

    def _suggested_wait_ms_for_empty_count(self, count: int) -> int:
        if count <= 1:
            return 5000
        if count <= 3:
            return 15000
        if count <= 6:
            return 30000
        return 60000
