"""Compact boundary creation."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .context_estimator import DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT
from .token_usage import normalize_sampling_usage


@dataclass(slots=True)
class CompactionService:
    """Build compact handoff records with LLM-first and deterministic fallback paths."""

    policy_version: str = "compact_boundary_v2"
    max_excerpt_chars: int = 1200
    max_tool_lines: int = 20
    max_compact_prompt_chars: int = 60000

    async def compact_async(
        self,
        session,
        context_messages: list[dict[str, Any]],
        chat_client,
        reason: str = "manual",
        phase: str = "manual",
        context_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = self._now()
        raw_messages = await self._load_raw_messages(session, context_messages)
        tool_records = await self._load_tool_records(session)
        previous = await self._load_latest_compaction(session)
        record = self.build_compaction(
            raw_messages,
            tool_records,
            previous_compaction=previous,
            created_at=created_at,
            reason=reason,
            phase=phase,
            strategy="deterministic_fallback",
        )
        try:
            response = await chat_client.create(
                messages=self._build_compact_prompt(context_messages),
                tools=None,
            )
            content = self._assistant_content(response).strip()
            if not content:
                raise ValueError("compact model returned empty handoff")
            record["strategy"] = "llm_inline"
            record["handoff_message"] = {"role": "assistant", "content": content}
            usage = self._sampling_usage(response, context_stats)
            if usage:
                record["usage"] = usage
                persist_usage = getattr(session, "persist_sampling_usage", None)
                if callable(persist_usage):
                    await persist_usage(usage)
        except Exception as exc:
            record["strategy"] = "deterministic_fallback"
            record["fallback_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }

        persist = getattr(session, "persist_compaction", None)
        if callable(persist):
            return await persist(record)
        return record

    def build_compaction(
        self,
        messages: list[dict[str, Any]],
        tool_records: list[dict[str, Any]] | None = None,
        previous_compaction: dict[str, Any] | None = None,
        created_at: str | None = None,
        reason: str = "manual",
        phase: str = "manual",
        strategy: str = "manual_deterministic",
    ) -> dict[str, Any]:
        created = created_at or self._now()
        boundary_index = self._latest_boundary_index(messages)
        source_start = boundary_index + 1 if boundary_index >= 0 else 0
        source_end = len(messages)
        source_messages = [
            dict(message)
            for message in messages[source_start:source_end]
            if not self._is_boundary(message)
        ]
        previous_handoff = self._previous_handoff(previous_compaction)
        tool_ids = self._collect_tool_call_ids(source_messages)
        tool_lines = self._render_tool_lines(tool_ids, tool_records or [])
        handoff = self._render_handoff(previous_handoff, source_messages, tool_lines)

        return {
            "id": uuid.uuid4().hex,
            "created_at": created,
            "strategy": strategy,
            "reason": reason,
            "phase": phase,
            "policy_version": self.policy_version,
            "source": {
                "message_start_index": source_start,
                "message_end_index_exclusive": source_end,
                "tool_call_ids": tool_ids,
                "history_digest": self._digest(source_messages, previous_compaction),
            },
            "handoff_message": {
                "role": "assistant",
                "content": handoff,
            },
            "usage": {},
        }

    def _build_compact_prompt(self, context_messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        payload = json.dumps(context_messages, ensure_ascii=False, sort_keys=True, default=str)
        payload = self._limit_prompt_payload(payload)
        system = (
            "You are compacting a coding-agent conversation into a source-bound handoff. "
            "Do not invent facts. Preserve concrete user goals, completed work, pending work, "
            "files, commands, tests, tool results, constraints, risks, and next steps. "
            "Write concise Markdown."
        )
        user = (
            "Create a compact handoff for the following model-visible context. "
            "The handoff will replace older context after a compact boundary.\n\n"
            "Required sections:\n"
            "- Current goal\n"
            "- Completed work\n"
            "- Pending work\n"
            "- Files, commands, and tests\n"
            "- Key tool results\n"
            "- User preferences and constraints\n"
            "- Risks and next checks\n\n"
            f"Context JSON:\n{payload}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def _load_raw_messages(self, session, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        load = getattr(session, "load_messages", None)
        if callable(load):
            try:
                messages = await load()
                if isinstance(messages, list):
                    return [dict(item) for item in messages if isinstance(item, dict)]
            except Exception:
                pass
        return [dict(item) for item in fallback if isinstance(item, dict)]

    async def _load_tool_records(self, session) -> list[dict[str, Any]]:
        get_records = getattr(session, "get_tool_records", None)
        if callable(get_records):
            try:
                records = await get_records()
                if isinstance(records, list):
                    return [dict(item) for item in records if isinstance(item, dict)]
            except Exception:
                pass
        return []

    async def _load_latest_compaction(self, session) -> dict[str, Any] | None:
        get_latest = getattr(session, "get_latest_compaction", None)
        if callable(get_latest):
            try:
                latest = await get_latest()
                return dict(latest) if isinstance(latest, dict) else None
            except Exception:
                return None
        return None

    def _assistant_content(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text
        choices = self._get(response, "choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            message = self._get(first, "message")
            content = self._get(message, "content")
            if isinstance(content, str):
                return content
        return ""

    def _sampling_usage(self, response: Any, context_stats: dict[str, Any] | None) -> dict[str, Any] | None:
        stats = context_stats or {}
        context_window = int(stats.get("context_window_tokens") or DEFAULT_CONTEXT_WINDOW_TOKENS)
        effective_window = int(
            stats.get("effective_context_window_tokens")
            or (context_window * DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT // 100)
        )
        return normalize_sampling_usage(
            response,
            sampling_kind="compact",
            context_window_tokens=context_window,
            effective_context_window_tokens=effective_window,
        )

    def _limit_prompt_payload(self, payload: str) -> str:
        if len(payload) <= self.max_compact_prompt_chars:
            return payload
        half = max(1, (self.max_compact_prompt_chars - 44) // 2)
        return payload[:half].rstrip() + "\n[compact_prompt_truncated]\n" + payload[-half:].lstrip()

    def _get(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _render_handoff(
        self,
        previous_handoff: str,
        source_messages: list[dict[str, Any]],
        tool_lines: list[str],
    ) -> str:
        last_user = self._last_content(source_messages, "user")
        last_assistant = self._last_content(source_messages, "assistant")
        lines = [
            "Context compacted.",
            "This is a deterministic handoff generated from persisted session events.",
        ]
        if previous_handoff:
            lines.extend(["", "Previous compact handoff:", self._excerpt(previous_handoff)])
        if last_user:
            lines.extend(["", "Latest user message:", self._excerpt(last_user)])
        if last_assistant:
            lines.extend(["", "Latest assistant message:", self._excerpt(last_assistant)])
        if tool_lines:
            lines.extend(["", "Tool calls:"])
            lines.extend(tool_lines)
        if len(lines) == 2:
            lines.append("No prior conversational messages were available in the compacted range.")
        return "\n".join(lines)

    def _render_tool_lines(self, tool_ids: list[str], tool_records: list[dict[str, Any]]) -> list[str]:
        records = {
            str(record.get("id")): record
            for record in tool_records
            if isinstance(record, dict) and record.get("id")
        }
        lines: list[str] = []
        for call_id in tool_ids[: self.max_tool_lines]:
            record = records.get(call_id, {})
            name = record.get("name") or "unknown"
            ok = record.get("ok")
            error_type = record.get("error_type")
            suffix = f", error_type={error_type}" if error_type else ""
            lines.append(f"- {call_id}: {name}, ok={ok}{suffix}")
        remaining = len(tool_ids) - len(lines)
        if remaining > 0:
            lines.append(f"- ... {remaining} additional tool call(s) omitted from handoff.")
        return lines

    def _collect_tool_call_ids(self, messages: list[dict[str, Any]]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for message in messages:
            role = message.get("role")
            if role == "tool":
                self._append_id(ordered, seen, message.get("tool_call_id"))
            meta = message.get("meta")
            if isinstance(meta, dict):
                self._collect_ids_from_tool_calls(ordered, seen, meta.get("tool_calls"))
            self._collect_ids_from_tool_calls(ordered, seen, message.get("tool_calls"))
        return ordered

    def _collect_ids_from_tool_calls(self, ordered: list[str], seen: set[str], tool_calls: Any) -> None:
        if not isinstance(tool_calls, list):
            return
        for item in tool_calls:
            if isinstance(item, dict):
                self._append_id(ordered, seen, item.get("id"))

    def _append_id(self, ordered: list[str], seen: set[str], call_id: Any) -> None:
        if not call_id:
            return
        text = str(call_id)
        if text in seen:
            return
        seen.add(text)
        ordered.append(text)

    def _latest_boundary_index(self, messages: list[dict[str, Any]]) -> int:
        for index in range(len(messages) - 1, -1, -1):
            if self._is_boundary(messages[index]):
                return index
        return -1

    def _is_boundary(self, message: dict[str, Any]) -> bool:
        meta = message.get("meta")
        return isinstance(meta, dict) and meta.get("kind") == "compact_boundary"

    def _previous_handoff(self, compaction: dict[str, Any] | None) -> str:
        if not isinstance(compaction, dict):
            return ""
        handoff = compaction.get("handoff_message")
        if not isinstance(handoff, dict):
            return ""
        content = handoff.get("content")
        return content if isinstance(content, str) else ""

    def _last_content(self, messages: list[dict[str, Any]], role: str) -> str:
        for message in reversed(messages):
            if message.get("role") != role:
                continue
            if role == "assistant" and message.get("tool_calls"):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
        return ""

    def _excerpt(self, text: str) -> str:
        if len(text) <= self.max_excerpt_chars:
            return text
        half = max(1, (self.max_excerpt_chars - 42) // 2)
        return text[:half].rstrip() + "\n[excerpt_truncated]\n" + text[-half:].lstrip()

    def _digest(self, source_messages: list[dict[str, Any]], previous_compaction: dict[str, Any] | None) -> str:
        payload = {
            "previous_compaction_id": (previous_compaction or {}).get("id"),
            "source_messages": source_messages,
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(text.encode("utf-8")).hexdigest()
