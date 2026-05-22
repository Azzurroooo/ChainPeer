"""Repository for persisting and loading summaries."""

from __future__ import annotations

import uuid
from typing import Any
from agent.infrastructure.persistence.session_files import SessionFiles

class SummaryRepository:
    def __init__(self, files: SessionFiles, tool_summary_path: str, conversation_summary_path: str):
        self._files = files
        self._tool_path = tool_summary_path
        self._conversation_path = conversation_summary_path

    def persist_tool_summary(self, ts: str, summary: dict) -> dict:
        record = dict(summary)
        if not record.get("call_id"):
            return record
        record.setdefault("id", uuid.uuid4().hex)
        record.setdefault("created_at", ts)
        record.setdefault("version", "1")
        self._files.append_jsonl(self._tool_path, record)
        return record

    def load_tool_summaries(self) -> list[dict[str, Any]]:
        return self._files.read_jsonl(self._tool_path)

    def persist_conversation_summary(self, ts: str, summary: dict) -> dict:
        record = dict(summary)
        record.setdefault("id", uuid.uuid4().hex)
        record.setdefault("created_at", ts)
        record.setdefault("version", "1")
        self._files.append_jsonl(self._conversation_path, record)
        return record

    def load_conversation_summaries(self) -> list[dict[str, Any]]:
        return self._files.read_jsonl(self._conversation_path)
