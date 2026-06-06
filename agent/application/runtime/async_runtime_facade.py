"""Facade for the asynchronous agent runtime."""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import RuntimeEvent, TurnStartedEvent, event_meta


class AsyncRuntimeFacade:
    """Facade exposing asynchronous entry points for session-bound turns."""

    def __init__(self, turn_runner: AsyncTurnRunner, session_store: AsyncSessionStore):
        self._turn_runner = turn_runner
        self._session_store = session_store
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize or load the session state. Safe to call multiple times."""
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await self._session_store.initialize()
            self._initialized = True

    def set_retry_callback(self, callback) -> None:
        """Set a callback invoked on LLM API retries: (attempt: int, exception: Exception) -> None."""
        self._turn_runner.set_retry_callback(callback)

    async def set_model(self, model: str) -> dict[str, bool]:
        """Switch the active chat model and persist the session metadata when supported."""
        await self.initialize()
        set_model = getattr(self._turn_runner, "set_model", None)
        runtime_updated = bool(set_model(model)) if callable(set_model) else False
        session_updated = False
        update_model = getattr(self._session_store, "update_model", None)
        if callable(update_model):
            await update_model(model)
            session_updated = True
        return {"runtime": runtime_updated, "session": session_updated}

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
        await self.initialize()
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
