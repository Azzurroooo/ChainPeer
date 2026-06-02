import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.infrastructure.config.settings import Config


@pytest.fixture(autouse=True)
def restore_config():
    attrs = {
        "SETTINGS": Config.SETTINGS,
        "SETTINGS_PATH": Config.SETTINGS_PATH,
        "SETTINGS_EXISTS": Config.SETTINGS_EXISTS,
        "OPENAI_API_KEY": Config.OPENAI_API_KEY,
        "OPENAI_API_BASE": Config.OPENAI_API_BASE,
        "OPENAI_USER_AGENT": Config.OPENAI_USER_AGENT,
        "DEFAULT_MODEL": Config.DEFAULT_MODEL,
        "MODEL_REASONING_EFFORT": Config.MODEL_REASONING_EFFORT,
        "CONTEXT_WINDOW_TOKENS": Config.CONTEXT_WINDOW_TOKENS,
        "EFFECTIVE_CONTEXT_WINDOW_PERCENT": Config.EFFECTIVE_CONTEXT_WINDOW_PERCENT,
        "AUTO_COMPACT_TOKEN_LIMIT": Config.AUTO_COMPACT_TOKEN_LIMIT,
        "AUTO_COMPACT_TOKEN_LIMIT_SCOPE": Config.AUTO_COMPACT_TOKEN_LIMIT_SCOPE,
        "AUTO_COMPACT_ENABLED": Config.AUTO_COMPACT_ENABLED,
    }
    yield
    for key, value in attrs.items():
        setattr(Config, key, value)


def test_config_reload_reads_settings_json(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": "gpt-5.5",
                "apiKey": "settings-key",
                "baseUrl": "https://openai945.cn/",
                "reasoningEffort": "xhigh",
                "contextWindow": 128000,
                "effectiveContextWindowPercent": 90,
                "autoCompactTokenLimit": 100000,
                "autoCompactTokenLimitScope": "body_after_prefix",
                "autoCompactEnabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHAINPEER_SETTINGS_PATH", str(path))

    Config.reload()

    assert Config.SETTINGS_PATH == str(path)
    assert Config.SETTINGS_EXISTS is True
    assert Config.OPENAI_API_KEY == "settings-key"
    assert Config.OPENAI_API_BASE == "https://openai945.cn/"
    assert Config.DEFAULT_MODEL == "gpt-5.5"
    assert Config.MODEL_REASONING_EFFORT == "xhigh"
    assert Config.CONTEXT_WINDOW_TOKENS == 128000
    assert Config.EFFECTIVE_CONTEXT_WINDOW_PERCENT == 90
    assert Config.AUTO_COMPACT_TOKEN_LIMIT == 100000
    assert Config.AUTO_COMPACT_TOKEN_LIMIT_SCOPE == "body_after_prefix"
    assert Config.AUTO_COMPACT_ENABLED is False


def test_config_validate_reports_settings_path_when_api_key_missing(tmp_path, monkeypatch):
    path = tmp_path / "missing.json"
    monkeypatch.setenv("CHAINPEER_SETTINGS_PATH", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    Config.reload()

    with pytest.raises(ValueError) as exc:
        Config.validate()

    assert str(path) in str(exc.value)
    assert "apiKey" in str(exc.value)


def test_config_get_async_client_uses_loaded_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"apiKey": "settings-key", "baseUrl": "https://example.com/v1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHAINPEER_SETTINGS_PATH", str(path))
    Config.reload()

    with patch("agent.infrastructure.config.settings.AsyncOpenAI") as mock_async_openai:
        Config.get_async_client()

    kwargs = mock_async_openai.call_args.kwargs
    assert kwargs["api_key"] == "settings-key"
    assert kwargs["base_url"] == "https://example.com/v1"
    assert kwargs["default_headers"] == {"User-Agent": "codex_cli_rs/0.0.0"}


def test_config_set_model_updates_settings_json(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"model": "old-model", "apiKey": "settings-key"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHAINPEER_SETTINGS_PATH", str(path))
    Config.reload()

    settings = Config.set_model("new-model")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert settings.model == "new-model"
    assert Config.DEFAULT_MODEL == "new-model"
    assert data["model"] == "new-model"
    assert data["apiKey"] == "settings-key"


def test_config_set_model_rejects_empty_model(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "old-model"}), encoding="utf-8")
    monkeypatch.setenv("CHAINPEER_SETTINGS_PATH", str(path))
    Config.reload()

    with pytest.raises(ValueError, match="Model name"):
        Config.set_model(" ")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "old-model"
