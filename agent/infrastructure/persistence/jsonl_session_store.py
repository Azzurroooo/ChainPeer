import json
import os
import uuid
from datetime import datetime, timezone


class JsonlSessionStore:
    def __init__(
        self,
        session_dir: str | None = None,
        session_id: str | None = None,
        resume_latest: bool = False,
        resume_mode: str = "summary",
        model: str | None = None,
        system_prompt: str = "",
        looks_like_tool_payload=None,
    ):
        self.session_dir = session_dir
        self.session_id = session_id
        self.resume_latest = resume_latest
        self.resume_mode = resume_mode
        self.model = model
        self.system_prompt = system_prompt
        self._looks_like_tool_payload = looks_like_tool_payload
        self.session_title = "Untitled"
        self._session_root = None
        self._session_paths = {}
        self._session_meta = None
        self._message_count = 0
        self._tool_call_count = 0
        self._last_preview = ""
        self._index_path = None
        self._current_workspace_root = None
        self.loaded_existing = False

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_chainpeer_home(self) -> str:
        custom_home = os.getenv("CHAINPEER_HOME")
        if custom_home:
            return os.path.abspath(os.path.expanduser(custom_home))
        return os.path.abspath(os.path.join(os.path.expanduser("~"), ".chainpeer"))

    def _default_session_root(self) -> str:
        return os.path.join(self._default_chainpeer_home(), "sessions")

    def _normalize_path(self, path: str | None) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    def _resolve_workspace_root_for_path(self, path: str) -> str:
        normalized = self._normalize_path(path)
        if not normalized:
            return normalized
        current = normalized
        while True:
            git_marker = os.path.join(current, ".git")
            if os.path.isdir(git_marker) or os.path.isfile(git_marker):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                return normalized
            current = parent

    def _resolve_workspace_root(self) -> str:
        return self._resolve_workspace_root_for_path(os.getcwd())

    def _new_session_id(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:8]}"

    def _get_session_paths(self, session_id: str) -> dict:
        base = os.path.join(self._session_root, session_id)
        return {
            "base": base,
            "meta": os.path.join(base, "meta.json"),
            "messages": os.path.join(base, "messages.jsonl"),
            "tool_calls": os.path.join(base, "tool_calls.jsonl"),
            "snapshots": os.path.join(base, "snapshots"),
        }

    def _load_json(self, path: str) -> dict | None:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_json(self, path: str, data: dict) -> None:
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
        os.replace(tmp, path)

    def _append_jsonl(self, path: str, data: dict) -> None:
        line = json.dumps(data, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()

    def _read_jsonl(self, path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        items = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        return items

    def _load_index(self) -> dict:
        index_path = self._index_path
        if not index_path and self._session_root:
            index_path = os.path.join(self._session_root, "index.json")
        if not index_path or not os.path.exists(index_path):
            return {"sessions": []}
        data = self._load_json(index_path)
        if not isinstance(data, dict) or "sessions" not in data:
            return {"sessions": []}
        if not isinstance(data.get("sessions"), list):
            return {"sessions": []}
        return data

    def _update_index(self) -> None:
        if not self._session_paths:
            return
        index_data = self._load_index()
        sessions = index_data.get("sessions", [])
        entry = {
            "id": self.session_id,
            "title": self._session_meta.get("title") if self._session_meta else self.session_title,
            "updated_at": self._session_meta.get("updated_at") if self._session_meta else self.now_iso(),
            "size": {"messages": self._message_count, "tool_calls": self._tool_call_count},
            "preview": self._last_preview,
            "workspace_root": self._session_meta.get("workspace_root") if self._session_meta else self._current_workspace_root,
        }
        updated = False
        for i, s in enumerate(sessions):
            if s.get("id") == self.session_id:
                sessions[i] = entry
                updated = True
                break
        if not updated:
            sessions.append(entry)
        index_data["sessions"] = sessions
        if self._index_path:
            self._write_json(self._index_path, index_data)

    def _create_session(self, session_id: str | None = None) -> None:
        if not session_id:
            session_id = self._new_session_id()
        self.session_id = session_id
        self._session_paths = self._get_session_paths(session_id)
        os.makedirs(self._session_paths["base"], exist_ok=True)
        os.makedirs(self._session_paths["snapshots"], exist_ok=True)
        open(self._session_paths["messages"], "a", encoding="utf-8").close()
        open(self._session_paths["tool_calls"], "a", encoding="utf-8").close()
        now = self.now_iso()
        self._message_count = 0
        self._tool_call_count = 0
        self._session_meta = {
            "schema_version": "1.1",
            "session_id": session_id,
            "title": self.session_title,
            "created_at": now,
            "updated_at": now,
            "model": self.model,
            "cwd": os.getcwd(),
            "workspace_root": self._current_workspace_root,
            "cli_args": {
                "resume_mode": self.resume_mode,
                "session_id": self.session_id,
                "resume_latest": self.resume_latest,
                "session_dir": self.session_dir,
            },
            "message_count": self._message_count,
            "tool_call_count": self._tool_call_count,
            "snapshot_count": 0,
            "tags": [],
        }
        self._write_json(self._session_paths["meta"], self._session_meta)
        self._update_index()

    def _load_message_records(self) -> list[dict]:
        if not self._session_paths:
            return []
        return self._read_jsonl(self._session_paths["messages"])

    def _load_tool_records(self) -> list[dict]:
        if not self._session_paths:
            return []
        return self._read_jsonl(self._session_paths["tool_calls"])

    def _load_tool_map(self) -> dict[str, dict]:
        tool_map: dict[str, dict] = {}
        for item in self._load_tool_records():
            if isinstance(item, dict) and item.get("id"):
                tool_map[item["id"]] = item
        return tool_map

    def _build_message_view(self, messages: list[dict] | None = None, tool_map: dict[str, dict] | None = None) -> list[dict]:
        if messages is None:
            messages = self._load_message_records()
        if tool_map is None:
            tool_map = self._load_tool_map()
        built_messages = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "tool":
                if self.resume_mode == "none":
                    continue
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
            built_messages = [{"role": "system", "content": self.system_prompt}]
        return built_messages

    def _load_session(self, session_id: str) -> None:
        self.session_id = session_id
        self._session_paths = self._get_session_paths(session_id)
        meta = self._load_json(self._session_paths["meta"])
        if not meta:
            self._create_session(session_id)
            return
        if not isinstance(meta.get("workspace_root"), str) or not meta.get("workspace_root", "").strip():
            raise ValueError(
                f"Session metadata missing workspace_root for id: {session_id}. "
                "Legacy session metadata is no longer supported."
            )
        self.loaded_existing = True
        self._session_meta = meta
        self._message_count = int(meta.get("message_count") or 0)
        self._tool_call_count = int(meta.get("tool_call_count") or 0)
        self.session_title = meta.get("title") or self.session_title

    def _workspace_root_from_entry(self, session_entry: dict) -> str:
        entry_root = session_entry.get("workspace_root")
        if isinstance(entry_root, str) and entry_root.strip():
            return self._resolve_workspace_root_for_path(entry_root)
        return ""

    def _find_latest_session_id(self) -> str | None:
        index_data = self._load_index()
        sessions = index_data.get("sessions", [])
        if not sessions:
            return None
        sessions = [s for s in sessions if isinstance(s, dict) and s.get("updated_at")]
        if not sessions:
            return None
        scoped = []
        current_root = self._normalize_path(self._current_workspace_root)
        for session in sessions:
            session_root = self._normalize_path(self._workspace_root_from_entry(session))
            if current_root and current_root == session_root:
                scoped.append(session)
        if not scoped:
            return None
        scoped.sort(key=lambda s: s.get("updated_at") or "")
        return scoped[-1].get("id")

    def ensure_session(self) -> None:
        self._current_workspace_root = self._resolve_workspace_root()
        if self.session_dir:
            self._session_root = os.path.abspath(self.session_dir)
            self._index_path = os.path.join(self._session_root, "index.json")
        else:
            chainpeer_home = self._default_chainpeer_home()
            self._session_root = os.path.join(chainpeer_home, "sessions")
            self._index_path = os.path.join(chainpeer_home, "session_index.json")
        os.makedirs(self._session_root, exist_ok=True)
        if self._index_path:
            os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
        if self.session_id and os.path.isdir(os.path.join(self._session_root, self.session_id)):
            self._load_session(self.session_id)
            self._export_session_env()
            return
        if self.resume_latest:
            latest_id = self._find_latest_session_id()
            if latest_id and os.path.isdir(os.path.join(self._session_root, latest_id)):
                self._load_session(latest_id)
                self._export_session_env()
                return
        if self.session_id:
            raise ValueError(f"Session not found for id: {self.session_id}")
        self._create_session(self.session_id)
        self._export_session_env()

    def _export_session_env(self) -> None:
        if self._session_root:
            os.environ["AGENT_SESSION_ROOT"] = self._session_root
        if self.session_id:
            os.environ["AGENT_SESSION_ID"] = self.session_id

    def initialize_history(self) -> None:
        has_persisted_system = any(
            isinstance(message, dict) and message.get("role") == "system"
            for message in self._load_message_records()
        )
        if not has_persisted_system:
            self.persist_message("system", self.system_prompt)

    def get_system_message(self) -> dict | None:
        for message in self._build_message_view():
            if message.get("role") == "system":
                return dict(message)
        return None

    def get_recent_messages(self, limit: int, include_system: bool = False) -> list[dict]:
        if limit <= 0:
            return []
        messages = self._build_message_view()
        if not include_system:
            messages = [message for message in messages if message.get("role") != "system"]
        return [dict(message) for message in messages[-limit:]]

    def get_messages_slice(
        self,
        start: int | None = None,
        end: int | None = None,
        roles: list[str] | None = None,
    ) -> list[dict]:
        messages = self._build_message_view()
        if roles:
            allowed_roles = set(roles)
            messages = [message for message in messages if message.get("role") in allowed_roles]
        return [dict(message) for message in messages[slice(start, end)]]

    def get_tool_records(self, limit: int | None = None, call_ids: list[str] | None = None) -> list[dict]:
        records = [dict(record) for record in self._load_tool_records() if isinstance(record, dict)]
        if call_ids:
            allowed_ids = set(call_ids)
            records = [record for record in records if record.get("id") in allowed_ids]
        if limit is not None:
            if limit <= 0:
                return []
            records = records[-limit:]
        return records

    def get_latest_conversation_summary(self) -> dict | None:
        return None

    def get_latest_context_snapshot(self) -> dict | None:
        return None

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
        if self.resume_mode == "full":
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False)
        if self.resume_mode == "none":
            return ""
        summarized = self._summarize_tool_result(result)
        if isinstance(summarized, str):
            return summarized
        return json.dumps(summarized, ensure_ascii=False)

    def persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict | None = None,
    ) -> None:
        if not self._session_paths:
            return
        msg = {"id": uuid.uuid4().hex, "ts": self.now_iso(), "role": role, "content": content or ""}
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        if tool_name:
            msg["tool_name"] = tool_name
        if meta:
            msg["meta"] = meta
        self._append_jsonl(self._session_paths["messages"], msg)
        self._message_count += 1
        if role == "assistant" and content:
            self._last_preview = content[:200]
        if role == "user" and self._session_meta and self._session_meta.get("title") in {None, "", "Untitled"}:
            self._session_meta["title"] = (content or "")[:40]
        if self._session_meta:
            self._session_meta["message_count"] = self._message_count
            self._session_meta["updated_at"] = self.now_iso()
            self._write_json(self._session_paths["meta"], self._session_meta)
        self._update_index()

    def _parse_tool_result(self, result: str):
        if isinstance(result, str) and self._looks_like_tool_payload and self._looks_like_tool_payload(result):
            try:
                return json.loads(result)
            except Exception:
                return result
        return result

    def _extract_tool_meta(self, payload):
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            data = payload.get("data")
            meta = {}
            if isinstance(data.get("stdout"), str):
                meta["stdout_size"] = len(data.get("stdout"))
            if isinstance(data.get("stderr"), str):
                meta["stderr_size"] = len(data.get("stderr"))
            if "exit_code" in data:
                meta["exit_code"] = data.get("exit_code")
            if meta:
                return meta
        return None

    def persist_tool_call(
        self,
        call_id: str,
        name: str,
        args: dict,
        raw_args: str,
        ts_start: str,
        ts_end: str,
        result: str,
    ) -> None:
        if not self._session_paths:
            return
        parsed = self._parse_tool_result(result)
        ok = None
        error_type = None
        error_message = None
        meta = None
        if isinstance(parsed, dict) and "ok" in parsed and "tool" in parsed:
            ok = bool(parsed.get("ok"))
            error_type = parsed.get("error_type")
            error_message = parsed.get("error")
            meta = self._extract_tool_meta(parsed)
        record = {
            "id": call_id,
            "ts_start": ts_start,
            "ts_end": ts_end,
            "name": name,
            "args": args,
            "raw_args": raw_args,
            "result": parsed,
            "ok": ok,
            "error_type": error_type,
            "error_message": error_message,
            "meta": meta,
        }
        self._append_jsonl(self._session_paths["tool_calls"], record)
        self._tool_call_count += 1
        if self._session_meta:
            self._session_meta["tool_call_count"] = self._tool_call_count
            self._session_meta["updated_at"] = self.now_iso()
            self._write_json(self._session_paths["meta"], self._session_meta)
        self._update_index()

