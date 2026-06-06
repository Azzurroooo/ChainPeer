"""Asynchronous turn runner coordinating the turn lifecycle via event streams."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator
import openai
from tenacity import RetryError

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.services import CompactionService, ContextManager, normalize_sampling_usage
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import (
    RuntimeEvent,
    AssistantDeltaEvent,
    AssistantMessageCompletedEvent,
    ContextBuiltEvent,
    SkillActivatedEvent,
    ToolRequestedEvent,
    TokenStatsUpdatedEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnCancelledEvent,
    event_meta,
)

from .message_stream_parser import MessageStreamParser
from agent.application.runtime.async_tool_call_processor import AsyncToolCallProcessor

class AsyncTurnRunner:
    """Manages the execution of a single conversational turn asynchronously."""

    def __init__(
        self,
        chat_client: AsyncChatClient,
        tool_processor: AsyncToolCallProcessor,
        stream_parser: MessageStreamParser,
        tool_schemas: list[dict],
        context_manager: ContextManager,
        debug: bool = False,
    ):
        self._chat_client = chat_client
        self._tool_processor = tool_processor
        self._stream_parser = stream_parser
        self._tool_schemas = tool_schemas
        self._context_manager = context_manager
        self._compaction_service = CompactionService()
        self._debug = debug

    def set_retry_callback(self, callback) -> None:
        """Set a callback invoked on LLM API retries: (attempt: int, exception: Exception) -> None."""
        if hasattr(self._chat_client, "on_retry"):
            self._chat_client.on_retry = callback

    def set_model(self, model: str) -> bool:
        set_model = getattr(self._chat_client, "set_model", None)
        if not callable(set_model):
            return False
        set_model(model)
        return True

    async def run_turn(
        self,
        session: AsyncSessionStore,
        cancellation_token: CancellationToken | None = None,
        turn_id: str = "",
    ) -> AsyncIterator[RuntimeEvent]:
        """Run the main conversation loop for a user turn asynchronously, yielding events."""
        
        turn_started_at = time.perf_counter()
        try:
            emitted_skill_names: set[str] = set()
            turn_active_skill_matches: list | None = None
            sampling_index = 0
            force_rescue_next_build = False
            context_length_recovery_count = 0
            while True:
                if cancellation_token and cancellation_token.is_cancelled:
                    yield self._cancelled_event(session, turn_id, cancellation_token)
                    return

                if turn_active_skill_matches is None:
                    turn_active_skill_matches = await self._resolve_turn_active_skills(session)

                context = await self._build_context(
                    session,
                    turn_active_skill_matches,
                    allow_rescue=force_rescue_next_build,
                )
                force_rescue_next_build = False
                context_stats = context.stats if isinstance(getattr(context, "stats", None), dict) else {}
                context_decisions = context.decisions if isinstance(getattr(context, "decisions", None), dict) else {}
                context_messages = context.messages if isinstance(getattr(context, "messages", None), list) else []
                yield ContextBuiltEvent(
                    **event_meta(session, turn_id),
                    message_count=len(context_messages),
                    stats=dict(context_stats),
                    decisions=dict(context_decisions),
                )
                for item in context_decisions.get("active_skills") or []:
                    skill_name = str(item.get("name") or "")
                    skill_key = skill_name.lower()
                    if not skill_key or skill_key in emitted_skill_names:
                        continue
                    emitted_skill_names.add(skill_key)
                    yield SkillActivatedEvent(
                        **event_meta(session, turn_id),
                        skill_name=skill_name,
                        reason=str(item.get("reason") or ""),
                        score=int(item.get("score") or 0),
                        source=str(item.get("source") or ""),
                        path=str(item.get("path") or ""),
                    )

                if context_decisions.get("auto_compact_token_limit_reached"):
                    phase = "pre_sampling" if sampling_index == 0 else "mid_turn"
                    context = await self._run_compact(
                        session=session,
                        context_messages=context_messages,
                        context_stats=context_stats,
                        reason="auto",
                        phase=phase,
                        active_skill_matches=turn_active_skill_matches,
                    )
                    context_stats = context.stats if isinstance(getattr(context, "stats", None), dict) else {}
                    context_decisions = context.decisions if isinstance(getattr(context, "decisions", None), dict) else {}
                    context_messages = context.messages if isinstance(getattr(context, "messages", None), list) else []
                    yield ContextBuiltEvent(
                        **event_meta(session, turn_id),
                        message_count=len(context_messages),
                        stats=dict(context_stats),
                        decisions=dict(context_decisions),
                    )
                
                try:
                    stream_response = self._chat_client.stream(
                        messages=context_messages,
                        tools=self._tool_schemas,
                        cancellation_token=cancellation_token
                    )

                    event_queue = asyncio.Queue()

                    async def _consume():
                        try:
                            async def _on_content_async(text: str):
                                await event_queue.put(
                                    AssistantDeltaEvent(
                                        **event_meta(session, turn_id),
                                        text=text,
                                    )
                                )

                            parsed = await self._stream_parser.consume_async_stream(
                                stream_response,
                                _on_content_async,
                                cancellation_token
                            )
                            if isinstance(parsed, tuple) and len(parsed) == 3:
                                content, calls, usage = parsed
                            else:
                                content, calls = parsed
                                usage = None
                            if usage is not None:
                                normalized_usage = normalize_sampling_usage(
                                    usage,
                                    sampling_kind="assistant",
                                    context_window_tokens=int(context_stats.get("context_window_tokens") or 258400),
                                    effective_context_window_tokens=int(
                                        context_stats.get("effective_context_window_tokens") or 245480
                                    ),
                                )
                                if normalized_usage:
                                    await self._persist_sampling_usage(session, normalized_usage)
                                    await event_queue.put(
                                        TokenStatsUpdatedEvent(
                                            **event_meta(session, turn_id),
                                            stats=normalized_usage,
                                        )
                                    )
                            return content, calls
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            await event_queue.put(e)
                            return "", []
                        finally:
                            try:
                                await event_queue.put(None)
                            except asyncio.CancelledError:
                                event_queue.put_nowait(None)

                    consume_task = asyncio.create_task(_consume())

                    try:
                        while True:
                            event = await event_queue.get()
                            if event is None:
                                break
                            if isinstance(event, Exception):
                                raise event
                            yield event
                    finally:
                        if not consume_task.done():
                            consume_task.cancel()
                            try:
                                await consume_task
                            except (asyncio.CancelledError, Exception):
                                pass

                    content_text, parsed_tool_calls = consume_task.result()
                    
                    if content_text:
                        await session.persist_message("assistant", content_text)
                        yield AssistantMessageCompletedEvent(
                            **event_meta(session, turn_id),
                            content_chars=len(content_text),
                        )
                        
                except openai.BadRequestError as e:
                    if "context_length_exceeded" in str(e) or "maximum context length" in str(e).lower():
                        context_length_recovery_count += 1
                        if context_length_recovery_count == 1:
                            await self._run_compact(
                                session=session,
                                context_messages=context_messages,
                                context_stats=context_stats,
                                reason="context_length_error",
                                phase="recovery",
                                active_skill_matches=turn_active_skill_matches,
                            )
                        else:
                            self._context_manager.reduce_hard_limit(factor=0.8)
                            force_rescue_next_build = True
                        continue
                    raise
                except RetryError as e:
                    error_msg = f"\n\n[APIUnavailableError: The AI provider is currently unreachable after multiple retries. Error: {e.last_attempt.exception()}]"
                    yield AssistantDeltaEvent(**event_meta(session, turn_id), text=error_msg)
                    yield TurnFailedEvent(
                        **event_meta(session, turn_id),
                        error=error_msg,
                        error_type="RetryError",
                    )
                    return

                if not parsed_tool_calls:
                    break
                sampling_index += 1
                    
                await session.persist_message(
                    "assistant",
                    "",
                    meta={"tool_calls": [{"id": item.call_id, "name": item.name} for item in parsed_tool_calls]},
                )

                for call in parsed_tool_calls:
                    yield ToolRequestedEvent(
                        **event_meta(session, turn_id),
                        tool_call_id=call.call_id,
                        tool_name=call.name,
                        args_preview=call.raw_args[:500],
                    )
                
                async for event in self._tool_processor.execute(
                    session=session,
                    tool_calls=parsed_tool_calls,
                    cancellation_token=cancellation_token,
                    turn_id=turn_id,
                ):
                    yield event
                        
            yield TurnCompletedEvent(
                **event_meta(session, turn_id),
                duration_ms=int((time.perf_counter() - turn_started_at) * 1000),
            )
            
        except asyncio.CancelledError as e:
            yield self._cancelled_event(session, turn_id, cancellation_token, fallback=str(e))
        except Exception as e:
            yield TurnFailedEvent(
                **event_meta(session, turn_id),
                error=str(e),
                error_type=type(e).__name__,
            )

    async def compact_context(
        self,
        session: AsyncSessionStore,
        reason: str = "manual",
        phase: str = "manual",
    ) -> dict:
        context = await self._build_context(session, active_skill_matches=None)
        stats = context.stats if isinstance(getattr(context, "stats", None), dict) else {}
        messages = context.messages if isinstance(getattr(context, "messages", None), list) else []
        return await self._compaction_service.compact_async(
            session=session,
            context_messages=messages,
            chat_client=self._chat_client,
            reason=reason,
            phase=phase,
            context_stats=stats,
        )

    async def _run_compact(
        self,
        *,
        session: AsyncSessionStore,
        context_messages: list[dict],
        context_stats: dict,
        reason: str,
        phase: str,
        active_skill_matches: list | None = None,
    ):
        await self._compaction_service.compact_async(
            session=session,
            context_messages=context_messages,
            chat_client=self._chat_client,
            reason=reason,
            phase=phase,
            context_stats=context_stats,
        )
        return await self._build_context(session, active_skill_matches=active_skill_matches)

    async def _build_context(
        self,
        session: AsyncSessionStore,
        active_skill_matches: list | None,
        allow_rescue: bool = False,
    ):
        try:
            return await self._context_manager.build_messages_async(
                session=session,
                active_skill_matches=active_skill_matches,
                allow_rescue=allow_rescue,
            )
        except TypeError as exc:
            if "allow_rescue" not in str(exc):
                raise
            return await self._context_manager.build_messages_async(
                session=session,
                active_skill_matches=active_skill_matches,
            )

    async def _persist_sampling_usage(self, session: AsyncSessionStore, usage: dict) -> None:
        persist_usage = getattr(session, "persist_sampling_usage", None)
        if callable(persist_usage):
            await self._best_effort(persist_usage, usage)
        update_window = getattr(session, "update_auto_compact_window_from_usage", None)
        if callable(update_window):
            await self._best_effort(update_window, usage)

    async def _best_effort(self, operation, *args) -> None:
        try:
            await operation(*args)
        except Exception:
            pass

    def _cancelled_event(
        self,
        session: AsyncSessionStore,
        turn_id: str,
        cancellation_token: CancellationToken | None,
        *,
        fallback: str = "",
    ) -> TurnCancelledEvent:
        reason = cancellation_token.reason if cancellation_token and cancellation_token.reason else fallback
        return TurnCancelledEvent(**event_meta(session, turn_id), reason=reason)

    async def _resolve_turn_active_skills(self, session: AsyncSessionStore) -> list:
        selector = getattr(self._context_manager, "select_active_skills_for_turn", None)
        if not callable(selector):
            return []
        user_message = await self._latest_user_content(session)
        try:
            return list(selector(user_message))
        except Exception:
            return []

    async def _latest_user_content(self, session: AsyncSessionStore) -> str:
        try:
            messages = await session.get_messages_slice()
        except Exception:
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
        return ""
