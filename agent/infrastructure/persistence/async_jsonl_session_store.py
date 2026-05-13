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
from agent.infrastructure.persistence.session_index_repository import SessionIndexRepository
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

    def _default_chainpeer_home(self) -> str:
        custom_home = os.getenv("CHAINPEER_HOME")
        if custom_home:
            return os.path.abspath(os.path.expanduser(custom_home))
        return os.path.abspath(os.path.join(os.path.expanduser("~"), ".chainpeer"))

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
        if self._session_dir:
            self._session_root = os.path.abspath(self._session_dir)
            self._index_path = os.path.join(self._session_root, "index.json")
        else:
            chainpeer_home = self._default_chainpeer_home()
            self._session_root = os.path.join(chainpeer_home, "sessions")
            self._index_path = os.path.join(chainpeer_home, "session_index.json")
            
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
            "snapshots": os.path.join(base, "snapshots"),
        }

    def _setup_repos(self):
        self._msg_repo = MessageRepository(self._files, self._session_paths["messages"])
        self._tool_repo = ToolCallRepository(self._files, self._session_paths["tool_calls"], looks_like_tool_payload)
        self._summary_repo = SummaryRepository(self._files, self._session_paths["tool_call_summaries"], self._session_paths["conversation_summaries"])

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

    def __del__(self):
        """Cleanup session environment variables when store is destroyed."""
        os.environ.pop("AGENT_SESSION_ROOT", None)
        os.environ.pop("AGENT_SESSION_ID", None)

    async def initialize(self) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._ensure_session_sync)
            await asyncio.to_thread(self._initialize_history_sync)
            
            # Inject session environment variables after successful initialization
            if self._session_root and self._session_id:
                os.environ["AGENT_SESSION_ROOT"] = str(self._session_root)
                os.environ["AGENT_SESSION_ID"] = str(self._session_id)

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
    ) -> None:
        async with self._write_lock:
            def _persist():
                if not self._tool_repo:
                    return
                self._tool_repo.persist_tool_call(call_id, name, parsed_args, raw_args, ts_start, ts_end, result_payload)
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
        result = tool_record.get("result")
        summarized = self._summarize_tool_result(result)
        if isinstance(summarized, str):
            return summarized
        return json.dumps(summarized, ensure_ascii=False)

    async def get_messages_slice(
        self,
        start: int | None = None,
        end: int | None = None,
        roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        def _get():
            messages = self._msg_repo.load_messages() if self._msg_repo else []
            tool_records = self._tool_repo.load_tool_calls() if self._tool_repo else []

            tool_map = {}
            for item in tool_records:
                if isinstance(item, dict) and item.get("id"):
                    tool_map[item["id"]] = item
                    
            built_messages = []
            for msg in messages:
                if not isinstance(msg, dict):
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

    async def persist_conversation_summary(self, summary_text: str, range_start_idx: int, range_end_idx: int) -> None:
        async with self._write_lock:
            def _persist():
                if not self._summary_repo:
                    return
                summary = {
                    "summary": summary_text,
                    "covered_turns": range_end_idx - range_start_idx,
                    "source_message_count": range_end_idx - range_start_idx
                }
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
                self._session_meta["latest_context_snapshot"] = dict(snapshot)
                self._session_meta["updated_at"] = self.now_iso()
                self._files.write_json(self._session_paths["meta"], self._session_meta)
                self._update_index()
            await asyncio.to_thread(_persist)
