"""Facade adapting the synchronous JsonlSessionStore to AsyncSessionStore via asyncio.to_thread."""

from __future__ import annotations

import asyncio
from typing import Any

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.infrastructure.persistence.jsonl_session_store import JsonlSessionStore


class AsyncJsonlSessionStoreFacade(AsyncSessionStore):
    """
    Wraps the synchronous JsonlSessionStore to provide an asynchronous interface.
    Uses asyncio.to_thread for potentially blocking file operations.
    """

    def __init__(self, sync_store: JsonlSessionStore):
        self._store = sync_store

    @property
    def session_id(self) -> str | None:
        return self._store.session_id

    @property
    def model(self) -> str | None:
        return self._store.model

    @property
    def system_prompt(self) -> str:
        return self._store.system_prompt

    def now_iso(self) -> str:
        return self._store.now_iso()

    async def initialize(self) -> None:
        # In the current implementation, JsonlSessionStore might do its initialization in __init__
        # or it creates session via _create_session. We ensure session is created here.
        if hasattr(self._store, "initialize"):
            await asyncio.to_thread(self._store.initialize)
        else:
            await asyncio.to_thread(self._store._create_session, self._store.session_id)

    async def persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._store.persist_message,
            role,
            content,
            tool_call_id,
            tool_name,
            meta
        )

    async def persist_tool_call(
        self,
        call_id: str,
        name: str,
        parsed_args: dict,
        raw_args: str,
        ts_start: str,
        ts_end: str,
        result_payload: str,
    ) -> None:
        await asyncio.to_thread(
            self._store.persist_tool_call,
            call_id,
            name,
            parsed_args,
            raw_args,
            ts_start,
            ts_end,
            result_payload
        )

    async def reconstruct_messages(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._store.reconstruct_messages)

    async def load_messages(self) -> list[dict[str, Any]]:
        # Map load_messages to _read_jsonl internally for now
        if hasattr(self._store, "load_messages"):
            return await asyncio.to_thread(self._store.load_messages)
        else:
            return await asyncio.to_thread(self._store._read_jsonl, self._store._session_paths.get("messages"))

    async def persist_conversation_summary(self, summary_text: str, range_start_idx: int, range_end_idx: int) -> None:
        await asyncio.to_thread(
            self._store.persist_conversation_summary,
            summary_text,
            range_start_idx,
            range_end_idx
        )

    async def list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._store.list_recent_sessions, limit)
