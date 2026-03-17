"""基础 Agent 实现 - 纯 OpenAI 版本"""
import json
import os
import traceback
import uuid
from datetime import datetime, timezone
from openai import OpenAI
from config.settings import Config
from tools import TOOLS, TOOL_SCHEMAS
from agent.prompts import SYSTEM_PROMPT
from utils import print_rainbow_logo
from tools.base import tool_ok, tool_error

class BasicAgent:
    def __init__(
        self,
        tools=None,
        debug: bool = False,
        session_mode: str = "write",
        session_dir: str | None = None,
        session_id: str | None = None,
        resume_latest: bool = False,
        resume_mode: str = "summary",
    ):
        self.client = Config.get_client()
        self.model = Config.DEFAULT_MODEL
        self.tool_schemas = tools or TOOL_SCHEMAS
        self.chat_history = []
        self.debug = debug
        self.session_mode = session_mode
        self.session_dir = session_dir
        self.session_id = session_id
        self.resume_latest = resume_latest
        self.resume_mode = resume_mode
        self.session_title = "Untitled"
        self._session_root = None
        self._session_paths = {}
        self._session_meta = None
        self._message_count = 0
        self._tool_call_count = 0
        self._last_preview = ""

    def _looks_like_tool_payload(self, s: str) -> bool:
        if not s:
            return False
        t = s.lstrip()
        if not t.startswith("{"):
            return False
        try:
            obj = json.loads(t)
        except Exception:
            return False
        return isinstance(obj, dict) and "ok" in obj and "tool" in obj

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_session_root(self) -> str:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sessions"))

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
            "index": os.path.join(self._session_root, "index.json"),
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
        index_path = self._session_paths.get("index") if self._session_paths else None
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
        if self.session_mode == "off" or not self._session_paths:
            return
        index_data = self._load_index()
        sessions = index_data.get("sessions", [])
        entry = {
            "id": self.session_id,
            "title": self._session_meta.get("title") if self._session_meta else self.session_title,
            "updated_at": self._session_meta.get("updated_at") if self._session_meta else self._utc_now_iso(),
            "size": {"messages": self._message_count, "tool_calls": self._tool_call_count},
            "preview": self._last_preview,
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
        self._write_json(self._session_paths["index"], index_data)

    def _create_session(self, session_id: str | None = None) -> None:
        if self.session_mode == "off":
            return
        if not session_id:
            session_id = self._new_session_id()
        self.session_id = session_id
        self._session_paths = self._get_session_paths(session_id)
        os.makedirs(self._session_paths["base"], exist_ok=True)
        os.makedirs(self._session_paths["snapshots"], exist_ok=True)
        open(self._session_paths["messages"], "a", encoding="utf-8").close()
        open(self._session_paths["tool_calls"], "a", encoding="utf-8").close()
        now = self._utc_now_iso()
        self._message_count = 0
        self._tool_call_count = 0
        self._session_meta = {
            "schema_version": "1.0",
            "session_id": session_id,
            "title": self.session_title,
            "created_at": now,
            "updated_at": now,
            "model": self.model,
            "cwd": os.getcwd(),
            "cli_args": {
                "session_mode": self.session_mode,
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

    def _load_session(self, session_id: str) -> None:
        self.session_id = session_id
        self._session_paths = self._get_session_paths(session_id)
        meta = self._load_json(self._session_paths["meta"])
        if not meta:
            self._create_session(session_id)
            return
        self._session_meta = meta
        self._message_count = int(meta.get("message_count") or 0)
        self._tool_call_count = int(meta.get("tool_call_count") or 0)
        self.session_title = meta.get("title") or self.session_title
        tool_calls = self._read_jsonl(self._session_paths["tool_calls"])
        tool_map = {}
        for item in tool_calls:
            if isinstance(item, dict) and item.get("id"):
                tool_map[item["id"]] = item
        messages = self._read_jsonl(self._session_paths["messages"])
        rebuilt = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "tool":
                if self.resume_mode == "none":
                    continue
                tool_call_id = msg.get("tool_call_id")
                content = self._build_tool_content(tool_map.get(tool_call_id))
                rebuilt.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
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
                rebuilt.append({"role": "assistant", "tool_calls": tool_msgs})
                if msg.get("content"):
                    rebuilt.append({"role": "assistant", "content": msg.get("content")})
                continue
            if role in {"system", "user", "assistant"}:
                rebuilt.append({"role": role, "content": msg.get("content", "")})
        if not rebuilt:
            rebuilt = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.chat_history = rebuilt

    def _find_latest_session_id(self) -> str | None:
        index_data = self._load_index()
        sessions = index_data.get("sessions", [])
        if not sessions:
            return None
        sessions = [s for s in sessions if isinstance(s, dict) and s.get("updated_at")]
        if not sessions:
            return None
        sessions.sort(key=lambda s: s.get("updated_at") or "")
        return sessions[-1].get("id")

    def _ensure_session(self) -> None:
        if self.session_mode == "off":
            return
        self._session_root = os.path.abspath(self.session_dir) if self.session_dir else self._default_session_root()
        os.makedirs(self._session_root, exist_ok=True)
        if self.session_mode == "readwrite" and (self.session_id or self.resume_latest):
            if self.session_id and os.path.isdir(os.path.join(self._session_root, self.session_id)):
                self._load_session(self.session_id)
                return
            if self.resume_latest:
                latest_id = self._find_latest_session_id()
                if latest_id and os.path.isdir(os.path.join(self._session_root, latest_id)):
                    self._load_session(latest_id)
                    return
            if self.session_id:
                self._create_session(self.session_id)
                return
        self._create_session(self.session_id)

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

    def _persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict | None = None,
    ) -> None:
        if self.session_mode == "off" or not self._session_paths:
            return
        msg = {"id": uuid.uuid4().hex, "ts": self._utc_now_iso(), "role": role, "content": content or ""}
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
            self._session_meta["updated_at"] = self._utc_now_iso()
            self._write_json(self._session_paths["meta"], self._session_meta)
        self._update_index()

    def _parse_tool_result(self, result: str):
        if isinstance(result, str) and self._looks_like_tool_payload(result):
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

    def _persist_tool_call(
        self,
        call_id: str,
        name: str,
        args: dict,
        raw_args: str,
        ts_start: str,
        ts_end: str,
        result: str,
    ) -> None:
        if self.session_mode == "off" or not self._session_paths:
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
            self._session_meta["updated_at"] = self._utc_now_iso()
            self._write_json(self._session_paths["meta"], self._session_meta)
        self._update_index()

    def _safe_execute_tool(self, name: str, args: dict, raw_args: str | None = None) -> str:
        if name not in TOOLS:
            return tool_error(name, f"Unknown tool: {name}", "ToolNotFound")
        try:
            result = TOOLS[name](**args)
            if isinstance(result, str) and self._looks_like_tool_payload(result):
                return result
            return tool_ok(name, result)
        except TypeError as e:
            meta = {}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return tool_error(name, str(e), type(e).__name__, meta=meta or None)
        except Exception as e:
            meta = {"traceback": traceback.format_exc()[-4000:]}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return tool_error(name, str(e), type(e).__name__, meta=meta)

    def run(self, query: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": query}]
        while True:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=self.tool_schemas, tool_choice="auto"
            )
            msg = resp.choices[0].message
            messages.append(msg)

            if msg.content and not msg.tool_calls:
                return msg.content

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    raw_args = tc.function.arguments or ""
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except Exception as e:
                        result = tool_error(tc.function.name, f"Invalid tool arguments JSON: {e}", "ToolArgsJSONError", meta={"raw_args": raw_args[:2000]})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                        continue
                    result = self._safe_execute_tool(tc.function.name, args, raw_args=raw_args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    def chat(self):
        print_rainbow_logo()
        if self.debug:
            print(f"Chain Peer v0.1(Debug Mode: {self.debug}) 输入 'quit' 退出")
        else:
            print(f"Chain Peer v0.1")
            print("Welcome back!")
        print("-" * 50)
        self._ensure_session()
        if not self.chat_history:
            self.chat_history = [{"role": "system", "content": SYSTEM_PROMPT}]
            self._persist_message("system", SYSTEM_PROMPT)

        while True:
            try:
                user_input = input("\n> ").strip()
            except KeyboardInterrupt:
                print("\n再见！👋")
                break
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("再见！👋")
                break
            if not user_input:
                continue

            print("\nAgent: ", end="", flush=True)
            self.chat_history.append({"role": "user", "content": user_input})
            self._persist_message("user", user_input)

            try:
                while True:
                    if self.debug:
                        resp = self.client.chat.completions.create(
                            model=self.model, messages=self.chat_history,
                            tools=self.tool_schemas, tool_choice="auto", stream=False
                        )
                        msg = resp.choices[0].message
                        print(msg)
                        if msg.content:
                            self.chat_history.append({"role": "assistant", "content": msg.content})
                            self._persist_message("assistant", msg.content)
                        
                        if msg.tool_calls:
                            self.chat_history.append(msg)
                            self._persist_message(
                                "assistant",
                                "",
                                meta={"tool_calls": [{"id": tc.id, "name": tc.function.name} for tc in msg.tool_calls]},
                            )
                            for tc in msg.tool_calls:
                                print(f"\n[Debug] Tool Call: {tc.function.name}({tc.function.arguments})")
                                raw_args = tc.function.arguments or ""
                                ts_start = self._utc_now_iso()
                                try:
                                    args = json.loads(raw_args) if raw_args else {}
                                except Exception as e:
                                    args = {}
                                    result = tool_error(tc.function.name, f"Invalid tool arguments JSON: {e}", "ToolArgsJSONError", meta={"raw_args": raw_args[:2000]})
                                    ts_end = self._utc_now_iso()
                                    self._persist_tool_call(tc.id, tc.function.name, args, raw_args, ts_start, ts_end, result)
                                    print(f"[Debug] Tool executed. Tool Result: {result}")
                                    self.chat_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                                    self._persist_message("tool", "", tool_call_id=tc.id, tool_name=tc.function.name)
                                    continue
                                result = self._safe_execute_tool(tc.function.name, args, raw_args=raw_args)
                                ts_end = self._utc_now_iso()
                                self._persist_tool_call(tc.id, tc.function.name, args, raw_args, ts_start, ts_end, result)
                                print(f"[Debug] Tool executed. Tool Result: {result}")
                                self.chat_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                                self._persist_message("tool", "", tool_call_id=tc.id, tool_name=tc.function.name)
                                
                                if not msg.content:
                                    print()
                        else:
                            break
                    else:
                        resp = self.client.chat.completions.create(
                            model=self.model, messages=self.chat_history,
                            tools=self.tool_schemas, tool_choice="auto", stream=True
                        )

                        tool_calls, content_parts = [], []

                        for chunk in resp:
                            delta = chunk.choices[0].delta
                            if delta.content:
                                print(delta.content, end="", flush=True)
                                content_parts.append(delta.content)
                            if delta.tool_calls:
                                for tc in delta.tool_calls:
                                    idx = tc.index
                                    while len(tool_calls) <= idx:
                                        tool_calls.append({"id": "", "name": "", "arguments": ""})
                                    if tc.id: tool_calls[idx]["id"] = tc.id
                                    if tc.function:
                                        if tc.function.name: tool_calls[idx]["name"] = tc.function.name
                                        if tc.function.arguments: tool_calls[idx]["arguments"] += tc.function.arguments

                        if content_parts:
                            content_text = "".join(content_parts)
                            self.chat_history.append({"role": "assistant", "content": content_text})
                            self._persist_message("assistant", content_text)

                        if tool_calls:
                            msg = {"role": "assistant", "tool_calls": [
                                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                for tc in tool_calls
                            ]}
                            self.chat_history.append(msg)
                            self._persist_message(
                                "assistant",
                                "",
                                meta={"tool_calls": [{"id": tc["id"], "name": tc["name"]} for tc in tool_calls]},
                            )

                            for tc in tool_calls:
                                raw_args = tc.get("arguments") or ""
                                ts_start = self._utc_now_iso()
                                try:
                                    args = json.loads(raw_args) if raw_args else {}
                                except Exception as e:
                                    args = {}
                                    result = tool_error(tc["name"], f"Invalid tool arguments JSON: {e}", "ToolArgsJSONError", meta={"raw_args": raw_args[:2000]})
                                    ts_end = self._utc_now_iso()
                                    self._persist_tool_call(tc["id"], tc["name"], args, raw_args, ts_start, ts_end, result)
                                    self.chat_history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                                    self._persist_message("tool", "", tool_call_id=tc["id"], tool_name=tc["name"])
                                    continue
                                result = self._safe_execute_tool(tc["name"], args, raw_args=raw_args)
                                ts_end = self._utc_now_iso()
                                self._persist_tool_call(tc["id"], tc["name"], args, raw_args, ts_start, ts_end, result)
                                self.chat_history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                                self._persist_message("tool", "", tool_call_id=tc["id"], tool_name=tc["name"])
                                print()
                            
                        else:
                            break

                print()

            except Exception as e:
                print(f"\nError: {e}")
