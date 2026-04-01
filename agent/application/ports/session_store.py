"""Session persistence port for application/runtime layers."""

from __future__ import annotations

from typing import Protocol


class SessionStore(Protocol):
    loaded_existing: bool

    def now_iso(self) -> str: ...

    def ensure_session(self) -> None: ...

    def initialize_history(self) -> None: ...

    def get_system_message(self) -> dict | None: ...

    def get_recent_messages(self, limit: int, include_system: bool = False) -> list[dict]: ...

    def get_messages_slice(
        self,
        start: int | None = None,
        end: int | None = None,
        roles: list[str] | None = None,
    ) -> list[dict]: ...

    def get_tool_records(self, limit: int | None = None, call_ids: list[str] | None = None) -> list[dict]: ...

    def get_latest_conversation_summary(self) -> dict | None: ...

    def get_latest_context_snapshot(self) -> dict | None: ...

    def persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict | None = None,
    ) -> None: ...

    def persist_tool_call(
        self,
        call_id: str,
        name: str,
        args: dict,
        raw_args: str,
        ts_start: str,
        ts_end: str,
        result: str,
    ) -> None: ...
