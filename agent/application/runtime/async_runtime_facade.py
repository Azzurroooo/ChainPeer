"""Facade for the asynchronous agent runtime."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import RuntimeEvent


class AsyncRuntimeFacade:
    """
    Facade exposing the primary asynchronous entry points for running agent turns.
    Replaces the legacy synchronous AgentRuntime as the default main path.
    """

    def __init__(self, turn_runner: AsyncTurnRunner, session_store: AsyncSessionStore):
        self._turn_runner = turn_runner
        self._session_store = session_store

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

        if query:
            await self._session_store.persist_message("user", query)

        async for event in self._turn_runner.run_turn(
            session=self._session_store,
            cancellation_token=cancellation_token
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
            async for event in self.run_turn(session_id=session_id, query=query):
                if isinstance(event, AssistantDeltaEvent):
                    final_text += event.text
            return final_text

        return asyncio.run(_run())
