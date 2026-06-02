"""Load user-level ChainPeer settings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
import uuid


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_USER_AGENT = "codex_cli_rs/0.0.0"
DEFAULT_CONTEXT_WINDOW = 258400
DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT = 95
DEFAULT_SETTINGS_TEMPLATE = {
    "model": "gpt-5.5",
    "apiKey": "",
    "baseUrl": "",
    "reasoningEffort": "xhigh",
    "contextWindow": DEFAULT_CONTEXT_WINDOW,
    "effectiveContextWindowPercent": DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT,
    "autoCompactTokenLimit": None,
    "autoCompactTokenLimitScope": "total",
    "autoCompactEnabled": True,
}


@dataclass(frozen=True)
class AppSettings:
    settings_path: Path
    settings_exists: bool
    model: str
    api_key: str
    base_url: str
    reasoning_effort: str
    context_window: int
    effective_context_window_percent: int
    auto_compact_token_limit: int | None
    auto_compact_token_limit_scope: str
    auto_compact_enabled: bool
    user_agent: str = DEFAULT_USER_AGENT


def default_settings_path() -> Path:
    override = os.getenv("CHAINPEER_SETTINGS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".chainpeer" / "settings.json"


def load_settings(path: str | Path | None = None) -> AppSettings:
    settings_path = Path(path).expanduser() if path else default_settings_path()
    data = _read_json_object(settings_path) if settings_path.exists() else {}

    return AppSettings(
        settings_path=settings_path,
        settings_exists=settings_path.exists(),
        model=_string(data, "model") or os.getenv("DEFAULT_MODEL", "").strip() or DEFAULT_MODEL,
        api_key=_configured_or_env(data, "apiKey", "OPENAI_API_KEY"),
        base_url=_string(data, "baseUrl") or os.getenv("OPENAI_API_BASE", "").strip() or DEFAULT_BASE_URL,
        reasoning_effort=_configured_or_env(data, "reasoningEffort", "MODEL_REASONING_EFFORT"),
        context_window=_int_configured_or_env(data, "contextWindow", "MODEL_CONTEXT_WINDOW", DEFAULT_CONTEXT_WINDOW),
        effective_context_window_percent=_int_configured_or_env(
            data,
            "effectiveContextWindowPercent",
            "EFFECTIVE_CONTEXT_WINDOW_PERCENT",
            DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT,
        ),
        auto_compact_token_limit=_optional_int_configured_or_env(
            data,
            "autoCompactTokenLimit",
            "MODEL_AUTO_COMPACT_TOKEN_LIMIT",
        ),
        auto_compact_token_limit_scope=(
            _string(data, "autoCompactTokenLimitScope")
            or os.getenv("MODEL_AUTO_COMPACT_TOKEN_LIMIT_SCOPE", "").strip()
            or "total"
        ),
        auto_compact_enabled=_bool_configured_or_env(data, "autoCompactEnabled", "AUTO_COMPACT_ENABLED", True),
        user_agent=DEFAULT_USER_AGENT,
    )


def ensure_user_settings_template() -> Path | None:
    if os.getenv("CHAINPEER_SETTINGS_PATH", "").strip():
        return None
    settings_path = default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings_path.exists():
        settings_path.write_text(
            json.dumps(DEFAULT_SETTINGS_TEMPLATE, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return settings_path


def save_settings_patch(patch: dict[str, Any], path: str | Path | None = None) -> AppSettings:
    if not isinstance(patch, dict):
        raise ValueError("Settings patch must be a JSON object")
    settings_path = Path(path).expanduser() if path else default_settings_path()
    data = _read_json_object(settings_path) if settings_path.exists() else dict(DEFAULT_SETTINGS_TEMPLATE)
    data.update(patch)
    _write_json_object(settings_path, data)
    return load_settings(settings_path)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid settings.json: {path} ({exc})") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid settings.json: {path} must contain a JSON object")
    return value


def _write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _configured_or_env(data: dict[str, Any], key: str, env_key: str) -> str:
    if key in data:
        return _string(data, key)
    return os.getenv(env_key, "").strip()


def _int_configured_or_env(data: dict[str, Any], key: str, env_key: str, default: int) -> int:
    value = data.get(key) if key in data else os.getenv(env_key, "").strip()
    if value in {None, ""}:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int_configured_or_env(data: dict[str, Any], key: str, env_key: str) -> int | None:
    value = data.get(key) if key in data else os.getenv(env_key, "").strip()
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_configured_or_env(data: dict[str, Any], key: str, env_key: str, default: bool) -> bool:
    value = data.get(key) if key in data else os.getenv(env_key, "").strip()
    if value in {None, ""}:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
