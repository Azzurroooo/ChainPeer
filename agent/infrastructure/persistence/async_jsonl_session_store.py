"""Async Jsonl Session Store."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.infrastructure.persistence.session_files import SessionFiles
from agent.infrastructure.persistence.message_repository import MessageRepository
from agent.infrastructure.persistence.tool_call_repository import ToolCallRepository
from agent.infrastructure.persistence.summary_repository import SummaryRepository
from agent.infrastructure.persistence.compaction_repository import CompactionRepository
from agent.infrastructure.persistence.session_index_repository import SessionIndexRepository
from agent.application.services.compaction_service import CompactionService
from agent.domain import looks_like_tool_payload


class AsyncJsonlSessionStore(AsyncSessionStore):
    """
    Asynchronous JsonlSessionStore that uses specific repositories for each domain concept.
    """

    def __init__(
        self,
        session_dir: str | None = None,
        session_id: str | None = None,
        resume_latest: bool = False,
        model: str | None = None,
        system_prompt: str = "",
    ):
        self._session_dir = session_dir
        self._session_id = session_id
        self._resume_latest = resume_latest
        self._model = model
        self._system_prompt = system_prompt
        
        self._session_root = None
        self._index_path = None
        self._session_paths = {}
        self._session_meta = None
        self._message_count = 0
        self._tool_call_count = 0
        self._last_preview = ""
        
        self._files = SessionFiles()
        self._msg_repo = None
        self._tool_repo = None
        self._summary_repo = None
        self._compaction_repo = None
        self._index_repo = None
        self._write_lock = asyncio.Lock()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def model(self) -> str | None:
        return self._model

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def default_chainpeer_home(cls) -> str:
        custom_home = os.getenv("CHAINPEER_HOME")
        if custom_home:
            return os.path.abspath(os.path.expanduser(custom_home))
        return os.path.abspath(os.path.join(os.path.expanduser("~"), ".chainpeer"))

    @classmethod
    def resolve_session_root(cls, session_dir: str | None = None) -> str:
        if session_dir:
            return os.path.abspath(os.path.expanduser(session_dir))
        return os.path.join(cls.default_chainpeer_home(), "sessions")

    def _resolve_workspace_root(self) -> str:
        current = os.path.normcase(os.path.realpath(os.path.abspath(os.getcwd())))
        while True:
            git_marker = os.path.join(current, ".git")
            if os.path.isdir(git_marker) or os.path.isfile(git_marker):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                return os.path.normcase(os.path.realpath(os.path.abspath(os.getcwd())))
            current = parent

    def _setup_paths(self):
        self._session_root = self.resolve_session_root(self._session_dir)
        if self._session_dir:
            self._index_path = os.path.join(self._session_root, "index.json")
        else:
            self._index_path = os.path.join(self.default_chainpeer_home(), "session_index.json")
            
        os.makedirs(self._session_root, exist_ok=True)
        if self._index_path:
            os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
            
        self._index_repo = SessionIndexRepository(self._files, self._index_path)

    def _get_session_paths(self, session_id: str) -> dict:
        base = os.path.join(self._session_root, session_id)
        return {
            "base": base,
            "meta": os.path.join(base, "meta.json"),
            "messages": os.path.join(base, "messages.jsonl"),
            "tool_calls": os.path.join(base, "tool_calls.jsonl"),
            "tool_call_summaries": os.path.join(base, "tool_call_summaries.jsonl"),
            "conversation_summaries": os.path.join(base, "conversation_summaries.jsonl"),
            "compactions": os.path.join(base, "compactions.jsonl"),
            "snapshots": os.path.join(base, "snapshots"),
        }

    def _setup_repos(self):
        self._msg_repo = MessageRepository(self._files, self._session_paths["messages"])
        self._tool_repo = ToolCallRepository(self._files, self._session_paths["tool_calls"], looks_like_tool_payload)
        self._summary_repo = SummaryRepository(self._files, self._session_paths["tool_call_summaries"], self._session_paths["conversation_summaries"])
        self._compaction_repo = CompactionRepository(self._files, self._session_paths["compactions"])

    def _create_session(self, session_id: str | None = None) -> None:
        if not session_id:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_id = f"{ts}_{uuid.uuid4().hex[:8]}"
            
        self._session_id = session_id
        self._session_paths = self._get_session_paths(session_id)
        
        os.makedirs(self._session_paths["base"], exist_ok=True)
        os.makedirs(self._session_paths["snapshots"], exist_ok=True)
        Path(self._session_paths["messages"]).touch()
        Path(self._session_paths["tool_calls"]).touch()
        Path(self._session_paths["tool_call_summaries"]).touch()
        Path(self._session_paths["conversation_summaries"]).touch()
        Path(self._session_paths["compactions"]).touch()
        
        self._setup_repos()
        
        now = self.now_iso()
        self._message_count = 0
        self._tool_call_count = 0
        
        self._session_meta = {
            "schema_version": "1.1",
            "session_id": session_id,
            "title": "Untitled",
            "created_at": now,
            "updated_at": now,
            "model": self.model,
            "cwd": os.getcwd(),
            "workspace_root": self._resolve_workspace_root(),
            "message_count": self._message_count,
            "tool_call_count": self._tool_call_count,
            "auto_compact_window": self._default_auto_compact_window(),
        }
        self._files.write_json(self._session_paths["meta"], self._session_meta)
        self._update_index()

    def _load_session(self, session_id: str) -> None:
        self._session_id = session_id
        self._session_paths = self._get_session_paths(session_id)
        meta = self._files.load_json(self._session_paths["meta"])
        if not meta:
            raise ValueError(f"Session data corrupted or missing meta.json for id: {session_id}")
            
        self._setup_repos()
        
        self._session_meta = meta
        self._session_meta.setdefault("auto_compact_window", self._default_auto_compact_window())
        self._message_count = int(meta.get("message_count") or 0)
        self._tool_call_count = int(meta.get("tool_call_count") or 0)

    def _find_latest_session_id(self) -> str | None:
        index_data = self._index_repo.load_index()
        sessions = index_data.get("sessions", [])
        if not sessions:
            return None
        sessions = [s for s in sessions if isinstance(s, dict) and s.get("updated_at")]
        if not sessions:
            return None
            
        scoped = []
        current_root = os.path.normcase(os.path.realpath(os.path.abspath(self._resolve_workspace_root())))
        for session in sessions:
            entry_root = session.get("workspace_root")
            if isinstance(entry_root, str) and entry_root.strip():
                session_root = os.path.normcase(os.path.realpath(os.path.abspath(entry_root)))
                if current_root == session_root:
                    scoped.append(session)
        if not scoped:
            return None
        scoped.sort(key=lambda s: s.get("updated_at") or "")
        return scoped[-1].get("id")

    def _update_index(self) -> None:
        if not self._index_repo or not self._session_meta:
            return
            
        entry = {
            "id": self._session_id,
            "title": self._session_meta.get("title", "Untitled"),
            "updated_at": self._session_meta.get("updated_at", self.now_iso()),
            "size": {"messages": self._message_count, "tool_calls": self._tool_call_count},
            "preview": self._last_preview,
            "workspace_root": self._session_meta.get("workspace_root"),
        }
        self._index_repo.update_index(entry)

    def _default_auto_compact_window(self) -> dict[str, Any]:
        return {
            "ordinal": 1,
            "prefill_input_tokens": None,
            "prefill_source": None,
        }

    def _auto_compact_window_sync(self) -> dict[str, Any]:
        if not isinstance(self._session_meta, dict):
            return self._default_auto_compact_window()
        window = self._session_meta.get("auto_compact_window")
        if not isinstance(window, dict):
            window = self._default_auto_compact_window()
            self._session_meta["auto_compact_window"] = window
        normalized = self._default_auto_compact_window()
        normalized.update(window)
        try:
            normalized["ordinal"] = max(1, int(normalized.get("ordinal") or 1))
        except (TypeError, ValueError):
            normalized["ordinal"] = 1
        prefill = normalized.get("prefill_input_tokens")
        if prefill is not None:
            try:
                normalized["prefill_input_tokens"] = max(0, int(prefill))
            except (TypeError, ValueError):
                normalized["prefill_input_tokens"] = None
        self._session_meta["auto_compact_window"] = normalized
        return dict(normalized)

    def _ensure_session_sync(self):
        self._setup_paths()
        
        if self._session_id:
            if os.path.isdir(os.path.join(self._session_root, self._session_id)):
                self._load_session(self._session_id)
                return
            # If a session ID is requested but not found, we create it with that ID
            # This allows the API to initiate new sessions dynamically by ID
            self._create_session(self._session_id)
            return

        if self._resume_latest:
            latest_id = self._find_latest_session_id()
            if latest_id and os.path.isdir(os.path.join(self._session_root, latest_id)):
                self._load_session(latest_id)
                return
            raise ValueError("No existing session found to resume.")

        self._create_session(None)

    def _initialize_history_sync(self):
        messages = self._msg_repo.load_messages() if self._msg_repo else []
        has_system = any(isinstance(m, dict) and m.get("role") == "system" for m in messages)
        if not has_system and self._system_prompt:
            self._msg_repo.persist_message(self.now_iso(), "system", self._system_prompt)
            self._message_count += 1
            if self._session_meta:
                self._session_meta["message_count"] = self._message_count
                self._session_meta["updated_at"] = self.now_iso()
                self._files.write_json(self._session_paths["meta"], self._session_meta)
            self._update_index()

    async def initialize(self) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._ensure_session_sync)
            await asyncio.to_thread(self._initialize_history_sync)
            
            if self._session_root and self._session_id:
                from agent.infrastructure.plans.store import set_active_session_context

                set_active_session_context(str(self._session_root), str(self._session_id))

    async def persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        async with self._write_lock:
            def _persist():
                if not self._msg_repo:
                    return
                self._msg_repo.persist_message(self.now_iso(), role, content, tool_call_id, tool_name, meta)
                self._message_count += 1
                if role == "assistant" and content:
                    self._last_preview = content[:200]
                if role == "user" and self._session_meta and self._session_meta.get("title") in {None, "", "Untitled"}:
                    self._session_meta["title"] = (content or "")[:40]
                if self._session_meta:
                    self._session_meta["message_count"] = self._message_count
                    self._session_meta["updated_at"] = self.now_iso()
                    self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()

            await asyncio.to_thread(_persist)

    async def persist_tool_call(
        self,
        call_id: str,
        name: str,
        parsed_args: dict,
        raw_args: str,
        ts_start: str,
        ts_end: str,
        result_payload: str,
        model_content: str | None = None,
        model_content_format: str | None = None,
        model_content_policy: dict[str, Any] | None = None,
        artifact_ref: str | None = None,
    ) -> None:
        async with self._write_lock:
            def _persist():
                if not self._tool_repo:
                    return
                self._tool_repo.persist_tool_call(
                    call_id,
                    name,
                    parsed_args,
                    raw_args,
                    ts_start,
                    ts_end,
                    result_payload,
                    model_content=model_content,
                    model_content_format=model_content_format,
                    model_content_policy=model_content_policy,
                    artifact_ref=artifact_ref,
                )
                self._tool_call_count += 1
                if self._session_meta:
                    self._session_meta["tool_call_count"] = self._tool_call_count
                    self._session_meta["updated_at"] = self.now_iso()
                    self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()

            await asyncio.to_thread(_persist)

    async def load_messages(self) -> list[dict[str, Any]]:
        def _load():
            return self._msg_repo.load_messages() if self._msg_repo else []
        return await asyncio.to_thread(_load)
        
    async def reconstruct_messages(self) -> list[dict[str, Any]]:
        return await self.get_messages_slice()

    def _truncate_value(self, value, limit: int, depth: int = 2):
        if depth <= 0:
            return value
        if isinstance(value, str):
            if len(value) <= limit:
                return value
            return value[:limit] + f"...(truncated:{len(value)})"
        if isinstance(value, list):
            return [self._truncate_value(v, limit, depth - 1) for v in value]
        if isinstance(value, dict):
            return {k: self._truncate_value(v, limit, depth - 1) for k, v in value.items()}
        return value

    def _summarize_tool_result(self, result):
        if isinstance(result, dict) and "ok" in result and "tool" in result:
            summarized = dict(result)
            if "data" in summarized:
                summarized["data"] = self._truncate_value(summarized["data"], 800)
            if "error" in summarized:
                summarized["error"] = self._truncate_value(summarized["error"], 800)
            return summarized
        return self._truncate_value(result, 800)

    def _build_tool_content(self, tool_record: dict | None) -> str:
        if not tool_record:
            return ""
        model_content = tool_record.get("model_content")
        if isinstance(model_content, str):
            return model_content
        result = tool_record.get("result")
        summarized = self._summarize_tool_result(result)
        if isinstance(summarized, str):
            return summarized
        return json.dumps(summarized, ensure_ascii=False)

    def _is_compact_boundary_message(self, message: dict[str, Any]) -> bool:
        meta = message.get("meta")
        return isinstance(meta, dict) and meta.get("kind") == "compact_boundary"

    def _latest_compact_boundary_index(self, messages: list[dict[str, Any]]) -> int:
        for index in range(len(messages) - 1, -1, -1):
            if self._is_compact_boundary_message(messages[index]):
                return index
        return -1

    def _latest_compaction_sync(self) -> dict[str, Any] | None:
        if not self._compaction_repo:
            return None
        return self._compaction_repo.get_latest_compaction()

    def _apply_latest_compact_boundary(
        self,
        messages: list[dict[str, Any]],
        compaction: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        boundary_index = self._latest_compact_boundary_index(messages)
        if boundary_index < 0:
            return [dict(message) for message in messages]

        projected = [
            dict(message)
            for message in messages[:boundary_index]
            if message.get("role") == "system"
        ]
        handoff = (compaction or {}).get("handoff_message")
        if isinstance(handoff, dict):
            role = handoff.get("role")
            content = handoff.get("content")
            if role in {"user", "assistant", "system"} and isinstance(content, str):
                projected.append({"role": role, "content": content})
        projected.extend(
            dict(message)
            for message in messages[boundary_index + 1 :]
            if not self._is_compact_boundary_message(message)
        )
        return projected

    async def get_messages_slice(
        self,
        start: int | None = None,
        end: int | None = None,
        roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        def _get():
            messages = self._msg_repo.load_messages() if self._msg_repo else []
            tool_records = self._tool_repo.load_tool_calls() if self._tool_repo else []
            messages = self._apply_latest_compact_boundary(messages, self._latest_compaction_sync())

            tool_map = {}
            for item in tool_records:
                if isinstance(item, dict) and item.get("id"):
                    tool_map[item["id"]] = item
                    
            built_messages = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                if self._is_compact_boundary_message(msg):
                    continue
                role = msg.get("role")
                if role == "tool":
                    tool_call_id = msg.get("tool_call_id")
                    content = self._build_tool_content(tool_map.get(tool_call_id))
                    built_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
                    continue
                if role == "assistant" and isinstance(msg.get("meta"), dict) and msg["meta"].get("tool_calls"):
                    tool_calls_meta = msg["meta"]["tool_calls"]
                    tool_msgs = []
                    for tc_meta in tool_calls_meta:
                        tc_id = tc_meta.get("id")
                        tc_name = tc_meta.get("name") or ""
                        tc_record = tool_map.get(tc_id, {})
                        raw_args = tc_record.get("raw_args") or ""
                        if not raw_args and isinstance(tc_record.get("args"), dict):
                            raw_args = json.dumps(tc_record.get("args"), ensure_ascii=False)
                        tool_msgs.append(
                            {"id": tc_id, "type": "function", "function": {"name": tc_name, "arguments": raw_args}}
                        )
                    built_messages.append({"role": "assistant", "tool_calls": tool_msgs})
                    if msg.get("content"):
                        built_messages.append({"role": "assistant", "content": msg.get("content")})
                    continue
                if role in {"system", "user", "assistant"}:
                    built_messages.append({"role": role, "content": msg.get("content", "")})
            if not built_messages:
                built_messages = [{"role": "system", "content": self._system_prompt}]
                
            if roles:
                allowed_roles = set(roles)
                built_messages = [message for message in built_messages if message.get("role") in allowed_roles]
            return [dict(message) for message in built_messages[slice(start, end)]]
            
        return await asyncio.to_thread(_get)

    async def persist_conversation_summary(self, summary: dict[str, Any]) -> None:
        async with self._write_lock:
            def _persist():
                if not self._summary_repo:
                    return
                record = self._summary_repo.persist_conversation_summary(self.now_iso(), summary)
                if self._session_meta:
                    self._session_meta["updated_at"] = self.now_iso()
                    self._session_meta["latest_conversation_summary"] = {
                        "id": record.get("id"),
                        "created_at": record.get("created_at"),
                        "covered_turns": record.get("covered_turns"),
                        "source_message_count": record.get("source_message_count"),
                    }
                    self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()

            await asyncio.to_thread(_persist)

    async def list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        def _list():
            self._setup_paths()
            index_data = self._index_repo.load_index() if self._index_repo else {"sessions": []}
            sessions = index_data.get("sessions", [])
            sessions = [s for s in sessions if isinstance(s, dict) and s.get("updated_at")]
            sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
            return sessions[:limit]
        return await asyncio.to_thread(_list)

    async def get_tool_records(self, limit: int | None = None, call_ids: list[str] | None = None) -> list[dict[str, Any]]:
        def _get():
            if not self._tool_repo:
                return []
            records = self._tool_repo.load_tool_calls()
            if call_ids:
                allowed_ids = set(call_ids)
                records = [record for record in records if record.get("id") in allowed_ids]
            if limit is not None and limit > 0:
                records = records[-limit:]
            return records
        return await asyncio.to_thread(_get)

    async def get_tool_summaries(self, call_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        def _get():
            if not self._summary_repo:
                return {}
            summaries = self._summary_repo.load_tool_summaries()
            if call_ids:
                allowed_ids = set(call_ids)
                summaries = [item for item in summaries if item.get("call_id") in allowed_ids]
            return {item["call_id"]: item for item in summaries if "call_id" in item}
        return await asyncio.to_thread(_get)

    async def persist_tool_summary(self, summary: dict[str, Any]) -> None:
        async with self._write_lock:
            def _persist():
                if not self._summary_repo:
                    return
                self._summary_repo.persist_tool_summary(self.now_iso(), summary)
                if self._session_meta:
                    self._session_meta["updated_at"] = self.now_iso()
                    self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()
            await asyncio.to_thread(_persist)

    async def get_latest_conversation_summary(self) -> dict[str, Any] | None:
        def _get():
            if not self._summary_repo:
                return None
            summaries = self._summary_repo.load_conversation_summaries()
            if not summaries:
                return None
            return dict(summaries[-1])
        return await asyncio.to_thread(_get)

    async def persist_context_snapshot(self, snapshot: dict[str, Any]) -> None:
        async with self._write_lock:
            def _persist():
                if not self._session_meta or not self._session_paths:
                    return
                lightweight_snapshot = dict(snapshot)
                lightweight_snapshot.pop("snapshot", None)
                self._session_meta["latest_context_snapshot"] = lightweight_snapshot
                self._session_meta["updated_at"] = self.now_iso()
                self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()
            await asyncio.to_thread(_persist)

    async def persist_sampling_usage(self, usage: dict[str, Any]) -> None:
        async with self._write_lock:
            def _persist():
                if not self._session_meta or not self._session_paths:
                    return
                latest = dict(usage or {})
                latest["updated_at"] = self.now_iso()
                self._session_meta["latest_sampling_usage"] = latest
                self._session_meta["updated_at"] = latest["updated_at"]
                self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()

            await asyncio.to_thread(_persist)

    async def get_latest_sampling_usage(self) -> dict[str, Any] | None:
        def _get():
            if not isinstance(self._session_meta, dict):
                return None
            usage = self._session_meta.get("latest_sampling_usage")
            return dict(usage) if isinstance(usage, dict) else None

        return await asyncio.to_thread(_get)

    async def get_auto_compact_window(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._auto_compact_window_sync)

    async def update_auto_compact_window_from_usage(self, usage: dict[str, Any]) -> None:
        async with self._write_lock:
            def _persist():
                if not self._session_meta or not self._session_paths:
                    return
                input_tokens = int((usage or {}).get("input_tokens") or 0)
                if input_tokens <= 0:
                    return
                window = self._auto_compact_window_sync()
                if window.get("prefill_source") == "server":
                    return
                window["prefill_input_tokens"] = input_tokens
                window["prefill_source"] = "server"
                self._session_meta["auto_compact_window"] = window
                self._session_meta["updated_at"] = self.now_iso()
                self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()

            await asyncio.to_thread(_persist)

    async def start_next_auto_compact_window(self) -> None:
        async with self._write_lock:
            def _persist():
                if not self._session_meta or not self._session_paths:
                    return
                window = self._auto_compact_window_sync()
                self._session_meta["auto_compact_window"] = {
                    "ordinal": int(window.get("ordinal") or 1) + 1,
                    "prefill_input_tokens": None,
                    "prefill_source": None,
                }
                self._session_meta["updated_at"] = self.now_iso()
                self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()

            await asyncio.to_thread(_persist)

    async def persist_compaction(self, compaction: dict[str, Any]) -> dict[str, Any]:
        async with self._write_lock:
            def _persist():
                if not self._compaction_repo or not self._msg_repo:
                    return dict(compaction)
                candidate = dict(compaction)
                candidate.setdefault("id", uuid.uuid4().hex)
                candidate.setdefault("created_at", self.now_iso())
                candidate.setdefault("policy_version", "compact_boundary_v1")
                record = self._compaction_repo.persist_compaction(candidate)
                compact_id = record.get("id")
                self._msg_repo.persist_message(
                    self.now_iso(),
                    "assistant",
                    "",
                    meta={"kind": "compact_boundary", "compact_id": compact_id},
                )
                self._message_count += 1
                if self._session_meta:
                    self._session_meta["message_count"] = self._message_count
                    self._session_meta["updated_at"] = self.now_iso()
                    self._session_meta["latest_compaction"] = {
                        "id": compact_id,
                        "created_at": record.get("created_at"),
                        "policy_version": record.get("policy_version"),
                        "source": record.get("source"),
                    }
                    self._session_meta["auto_compact_window"] = {
                        "ordinal": int(self._auto_compact_window_sync().get("ordinal") or 1) + 1,
                        "prefill_input_tokens": None,
                        "prefill_source": None,
                    }
                    self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()
                return record

            return await asyncio.to_thread(_persist)

    async def get_latest_compaction(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._latest_compaction_sync)

    async def compact_context(self) -> dict[str, Any]:
        def _build():
            messages = self._msg_repo.load_messages() if self._msg_repo else []
            tool_records = self._tool_repo.load_tool_calls() if self._tool_repo else []
            previous = self._latest_compaction_sync()
            return CompactionService().build_compaction(
                messages=messages,
                tool_records=tool_records,
                previous_compaction=previous,
                created_at=self.now_iso(),
            )

        record = await asyncio.to_thread(_build)
        return await self.persist_compaction(record)
