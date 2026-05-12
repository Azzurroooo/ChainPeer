"""Asynchronous turn runner coordinating the turn lifecycle via event streams."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
import openai
from tenacity import RetryError

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.services import ContextManager
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import (
    RuntimeEvent,
    AssistantDeltaEvent,
    AssistantMessageCompletedEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnCancelledEvent
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
        self._debug = debug

    def set_retry_callback(self, callback) -> None:
        """Set a callback invoked on LLM API retries: (attempt: int, exception: Exception) -> None."""
        if hasattr(self._chat_client, "on_retry"):
            self._chat_client.on_retry = callback

    async def run_turn(
        self,
        session: AsyncSessionStore,
        cancellation_token: CancellationToken | None = None
    ) -> AsyncIterator[RuntimeEvent]:
        """Run the main conversation loop for a user turn asynchronously, yielding events."""
        
        try:
            while True:
                if cancellation_token and cancellation_token.is_cancelled:
                    yield TurnCancelledEvent(ts=session.now_iso(), reason=cancellation_token.reason)
                    return
                
                context = await self._context_manager.build_messages_async(session=session)
                
                try:
                    # We always use stream=True for the async runner to provide real-time events
                    stream_response = self._chat_client.stream(
                        messages=context.messages,
                        tools=self._tool_schemas,
                        cancellation_token=cancellation_token
                    )
                    
                    # Use the parser to consume the async stream and handle merging tool call chunks
                    async def _on_content(text: str):
                        yield AssistantDeltaEvent(ts=session.now_iso(), text=text)

                    # We can't directly yield from inside a callback easily without an async generator queue.
                    # Let's collect them directly in an async generator wrapper or just use the parser logic.
                    # Since we want to yield events *as* they arrive, we'll write a small adapter for the stream parser.
                    # To keep it clean, we'll iterate through the stream, manually emitting DeltaEvents,
                    # but delegating the chunk merging to the stream_parser's unified logic.
                    
                    # Queue-based bridge: producer consumes the async stream, consumer yields events.
                    # Sentinel (None) is guaranteed via put_nowait in finally to survive CancelledError.
                    event_queue = asyncio.Queue()

                    async def _consume():
                        try:
                            async def _on_content_async(text: str):
                                await event_queue.put(AssistantDeltaEvent(ts=session.now_iso(), text=text))

                            # Make sure we AWAIT consume_async_stream, not just return the coroutine!
                            content, calls = await self._stream_parser.consume_async_stream(
                                stream_response,
                                _on_content_async,
                                cancellation_token
                            )
                            return content, calls
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
                        yield AssistantMessageCompletedEvent(ts=session.now_iso())
                        
                except openai.BadRequestError as e:
                    if "context_length_exceeded" in str(e) or "maximum context length" in str(e).lower():
                        self._context_manager.reduce_hard_limit(factor=0.8)
                        continue
                    raise
                except RetryError as e:
                    error_msg = f"\n\n[APIUnavailableError: The AI provider is currently unreachable after multiple retries. Error: {e.last_attempt.exception()}]"
                    yield AssistantDeltaEvent(ts=session.now_iso(), text=error_msg)
                    yield TurnFailedEvent(ts=session.now_iso(), error=error_msg)
                    return

                if not parsed_tool_calls:
                    break
                    
                await session.persist_message(
                    "assistant",
                    "",
                    meta={"tool_calls": [{"id": item.call_id, "name": item.name} for item in parsed_tool_calls]},
                )
                
                # Execute tools and yield their events
                request_id = session.now_iso()
                
                async for event in self._tool_processor.execute(
                    session=session,
                    tool_calls=parsed_tool_calls,
                    cancellation_token=cancellation_token
                ):
                    yield event
                        
            yield TurnCompletedEvent(ts=session.now_iso())
            
        except asyncio.CancelledError as e:
            yield TurnCancelledEvent(ts=session.now_iso(), reason=str(e))
        except Exception as e:
            # We don't have session.now_iso() guaranteed here, but we try
            ts = session.now_iso() if hasattr(session, 'now_iso') else "unknown"
            yield TurnFailedEvent(ts=ts, error=str(e))
