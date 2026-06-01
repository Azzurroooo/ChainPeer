"""Facade for the asynchronous agent runtime."""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import RuntimeEvent, TurnStartedEvent, event_meta


class AsyncRuntimeFacade:
    """
    Facade exposing the primary asynchronous entry points for running agent turns.
    Replaces the legacy synchronous AgentRuntime as the default main path.
    """

    def __init__(self, turn_runner: AsyncTurnRunner, session_store: AsyncSessionStore):
        self._turn_runner = turn_runner
        self._session_store = session_store
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize or load the session state. Safe to call multiple times."""
        if not self._initialized:
            await self._session_store.initialize()
            self._initialized = True

    def set_retry_callback(self, callback) -> None:
        """Set a callback invoked on LLM API retries: (attempt: int, exception: Exception) -> None."""
        self._turn_runner.set_retry_callback(callback)

    async def compact_context(self, reason: str = "manual") -> dict:
        """Manually compact the current session through the turn runner."""
        await self.initialize()
        compact = getattr(self._turn_runner, "compact_context", None)
        if not callable(compact):
            compact_session = getattr(self._session_store, "compact_context", None)
            if callable(compact_session):
                return await compact_session()
            raise RuntimeError("Compact is not supported by this runtime.")
        return await compact(self._session_store, reason=reason, phase="manual")

    async def run_turn(
        self,
        session_id: str | None = None,
        query: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """
        Run a single conversational turn asynchronously, yielding runtime events.

        Note: session_id is accepted for API compatibility but the session bound to
        this facade at construction time is always used. The caller is responsible
        for constructing one facade per session.
        """
        await self._session_store.initialize()
        turn_id = uuid.uuid4().hex

        if query:
            await self._session_store.persist_message("user", query)

        yield TurnStartedEvent(
            **event_meta(self._session_store, turn_id),
            user_message_chars=len(query or ""),
        )

        async for event in self._turn_runner.run_turn(
            session=self._session_store,
            cancellation_token=cancellation_token,
            turn_id=turn_id,
        ):
            yield event

    def run_query_sync(self, query: str, session_id: str | None = None) -> str:
        """
        Synchronous compatibility layer for running a query.
        Returns the final assistant response string.
        """
        async def _run():
            from agent.domain.events import AssistantDeltaEvent
            final_text = ""
            try:
                async for event in self.run_turn(session_id=session_id, query=query):
                    if isinstance(event, AssistantDeltaEvent):
                        final_text += event.text
            except Exception as e:
                return f"Error: {str(e)}"
            return final_text

        return asyncio.run(_run())
