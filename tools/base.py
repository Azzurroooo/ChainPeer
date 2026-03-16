"""基础工具定义"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Optional

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def tool_ok(tool: str, data: Any = None, meta: Optional[dict[str, Any]] = None) -> str:
    payload: dict[str, Any] = {"ok": True, "tool": tool, "data": data, "ts": _utc_now_iso()}
    if meta is not None:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False)

def tool_error(tool: str, error: str, error_type: Optional[str] = None, meta: Optional[dict[str, Any]] = None) -> str:
    payload: dict[str, Any] = {"ok": False, "tool": tool, "error": error, "ts": _utc_now_iso()}
    if error_type:
        payload["error_type"] = error_type
    if meta is not None:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False)
