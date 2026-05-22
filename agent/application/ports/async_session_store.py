"""Asynchronous interface for session persistence."""

from __future__ import annotations

from typing import Protocol, Any


class AsyncSessionStore(Protocol):
    """Protocol for asynchronously persisting session state and history."""

    @property
    def session_id(self) -> str | None:
        ...

    @property
    def model(self) -> str | None:
        ...

    @property
    def system_prompt(self) -> str:
        ...

    def now_iso(self) -> str:
        ...

    async def initialize(self) -> None:
        """Initialize or load the session state."""
        ...

    async def persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Persist a single chat message asynchronously."""
        ...

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
        """Persist tool call execution details asynchronously."""
        ...

    async def reconstruct_messages(self) -> list[dict[str, Any]]:
        """Reconstruct message history for LLM context.

        Semantically identical to ``get_messages_slice()`` with default args.
        Kept as a named alias for callers that need the full conversation
        specifically for model input, as opposed to arbitrary slice queries.
        """
        ...

    async def load_messages(self) -> list[dict[str, Any]]:
        """Load all raw messages asynchronously."""
        ...

    async def persist_conversation_summary(self, summary: dict[str, Any]) -> None:
        """Persist a conversation summary asynchronously."""
        ...

    async def list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recently updated sessions asynchronously."""
        ...

    async def get_messages_slice(
        self,
        start: int | None = None,
        end: int | None = None,
        roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get a slice of messages asynchronously."""
        ...

    async def get_tool_records(self, limit: int | None = None, call_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Get tool records asynchronously."""
        ...

    async def get_tool_summaries(self, call_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """Get tool summaries asynchronously."""
        ...

    async def persist_tool_summary(self, summary: dict[str, Any]) -> None:
        """Persist a tool summary asynchronously."""
        ...

    async def get_latest_conversation_summary(self) -> dict[str, Any] | None:
        """Get the latest conversation summary asynchronously."""
        ...

    async def persist_context_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Persist a context snapshot asynchronously."""
        ...
