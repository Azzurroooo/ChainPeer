import asyncio
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.interfaces.cli.chat_cli import ChatCLI
from agent.interfaces.cli.ui import GitPromptStatus
from agent.interfaces.cli.commands import SlashCommandContext, SlashCommandRouter
from agent.infrastructure.config import Config


@pytest.fixture(autouse=True)
def restore_config_state():
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


class FakeSession:
    session_id = "session_1"
    model = "model_a"
    compact_called = False

    async def get_messages_slice(self):
        return [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]

    async def compact_context(self):
        self.compact_called = True
        return {
            "id": "compact_1",
            "source": {
                "message_start_index": 0,
                "message_end_index_exclusive": 2,
                "tool_call_ids": ["call_1"],
            },
        }

    async def get_latest_sampling_usage(self):
        return None

    async def list_recent_sessions(self, limit=10):
        return []


class FakeRuntime:
    def __init__(self):
        self.called = False
        self.compact_called = False
        self.model = None

    def run_turn(self, query=None, cancellation_token=None):
        self.called = True
        return EmptyStream()

    async def compact_context(self, reason="manual"):
        self.compact_called = True
        return {
            "id": "runtime_compact_1",
            "source": {
                "message_start_index": 0,
                "message_end_index_exclusive": 2,
                "tool_call_ids": [],
            },
        }

    async def set_model(self, model):
        self.model = model
        return {"runtime": True, "session": False}


class EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def aclose(self):
        return None


def _context(session=None):
    return SlashCommandContext(runtime=FakeRuntime(), session=session or FakeSession(), debug=True)


@pytest.mark.asyncio
async def test_help_returns_command_list() -> None:
    result = await SlashCommandRouter().execute("/help", _context())

    assert "/status" in result.text
    assert "Show session status" in result.text
    assert "/doctor" in result.text
    assert "/skill" in result.text
    assert "/clear" in result.text
    assert "/draft" in result.text
    assert "alias: /quit" in result.text
    assert result.should_exit is False


@pytest.mark.asyncio
async def test_help_returns_command_specific_usage() -> None:
    result = await SlashCommandRouter().execute("/help model", _context())

    assert result.text.startswith("/model")
    assert "Show or change the active model" in result.text
    assert "usage: /model | /model set <model>" in result.text


@pytest.mark.asyncio
async def test_help_accepts_command_alias() -> None:
    result = await SlashCommandRouter().execute("/help quit", _context())

    assert result.text.startswith("/exit")
    assert "aliases: /quit" in result.text


@pytest.mark.asyncio
async def test_help_reports_unknown_command() -> None:
    result = await SlashCommandRouter().execute("/help missing", _context())

    assert "Unknown command: /missing" in result.text
    assert "/help" in result.text


@pytest.mark.asyncio
async def test_help_rejects_too_many_args() -> None:
    result = await SlashCommandRouter().execute("/help model now", _context())

    assert result.text == "Usage: /help [command]"


def test_router_exposes_sorted_command_names() -> None:
    names = SlashCommandRouter().command_names()

    assert names == sorted(names)
    assert "help" in names
    assert "status" in names
    assert "sessions" in names


def test_router_exposes_command_descriptions() -> None:
    infos = SlashCommandRouter().command_infos()
    descriptions = {info.name: info.description for info in infos}
    usages = {info.name: info.usage for info in infos}

    assert [info.name for info in infos] == sorted(descriptions)
    assert descriptions["status"] == "Show session status"
    assert descriptions["model"] == "Show or change the active model"
    assert descriptions["clear"] == "Clear terminal output"
    assert descriptions["draft"] == "Show saved input draft"
    assert usages["sessions"] == "/sessions [limit]"


@pytest.mark.asyncio
async def test_sessions_lists_recent_sessions_with_current_marker() -> None:
    class SessionWithRecent(FakeSession):
        session_id = "session_2"

        def __init__(self):
            self.requested_limit = None

        async def list_recent_sessions(self, limit=10):
            self.requested_limit = limit
            return [
                {
                    "id": "session_2",
                    "title": "Current task",
                    "updated_at": "2026-06-02T01:02:03+00:00",
                    "size": {"messages": 4, "tool_calls": 1},
                    "preview": "latest answer",
                },
                {
                    "id": "session_1",
                    "title": "Older task",
                    "updated_at": "2026-06-01T01:02:03+00:00",
                    "size": {"messages": 2, "tool_calls": 0},
                    "preview": "",
                },
            ]

    session = SessionWithRecent()
    result = await SlashCommandRouter().execute("/sessions 5", _context(session=session))

    assert session.requested_limit == 5
    assert "Recent sessions:" in result.text
    assert "session_2 (current)" in result.text
    assert "4 msg, 1 tool" in result.text
    assert "latest answer" in result.text
    assert "python main.py --session <id>" in result.text


@pytest.mark.asyncio
async def test_sessions_reports_no_recent_sessions() -> None:
    result = await SlashCommandRouter().execute("/sessions", _context())

    assert result.text == "No recent sessions."


@pytest.mark.asyncio
async def test_sessions_rejects_invalid_limit() -> None:
    result = await SlashCommandRouter().execute("/sessions many", _context())

    assert result.text == "Usage: /sessions [limit]"


@pytest.mark.asyncio
async def test_sessions_handles_unsupported_session_store() -> None:
    class UnsupportedSession:
        session_id = "session_1"
        model = "model_a"

    result = await SlashCommandRouter().execute("/sessions", _context(session=UnsupportedSession()))

    assert result.text == "Sessions are not supported by this session store."


@pytest.mark.asyncio
async def test_unknown_command_returns_friendly_error() -> None:
    result = await SlashCommandRouter().execute("/missing", _context())

    assert "Unknown command: /missing" in result.text
    assert "/help" in result.text


@pytest.mark.asyncio
async def test_status_shows_session_model_debug_and_message_count() -> None:
    result = await SlashCommandRouter().execute("/status", _context())

    assert "Session: session_1" in result.text
    assert "Model: model_a" in result.text
    assert "Debug: true" in result.text
    assert "Messages: 2" in result.text


@pytest.mark.asyncio
async def test_status_shows_git_branch(monkeypatch) -> None:
    class FakeGitProvider:
        def __init__(self, *args, **kwargs):
            pass

        def current(self):
            return GitPromptStatus(branch="main", dirty=True)

    monkeypatch.setattr("agent.interfaces.cli.ui.GitPromptStatusProvider", FakeGitProvider)

    result = await SlashCommandRouter().execute("/status", _context())

    assert "Git: main*" in result.text


@pytest.mark.asyncio
async def test_status_shows_latest_sampling_usage() -> None:
    class UsageSession(FakeSession):
        async def get_latest_sampling_usage(self):
            return {
                "input_tokens": 121300,
                "effective_context_window_tokens": 245480,
                "context_usage_percent": 121300 / 245480,
                "cached_input_tokens": 98700,
                "cache_hit_rate": 98700 / 121300,
                "output_tokens": 2100,
            }

    result = await SlashCommandRouter().execute("/status", _context(session=UsageSession()))

    assert "Last sampling:" in result.text
    assert "input: 121.3k / 245.5k" in result.text
    assert "cached: 98.7k (81.4%)" in result.text


@pytest.mark.asyncio
async def test_status_shows_recent_tool_summaries() -> None:
    class ToolSession(FakeSession):
        async def get_tool_records(self, limit=None, call_ids=None):
            return [
                {
                    "name": "bash",
                    "ok": True,
                    "ts_end": "2026-06-02T01:02:03.000000+00:00",
                    "meta": {"exit_code": 0},
                },
                {
                    "name": "read_file",
                    "ok": False,
                    "error_type": "FileNotFoundError",
                    "ts_end": "2026-06-02T01:03:04.000000+00:00",
                    "meta": {"stdout_size": 1200},
                },
            ]

    result = await SlashCommandRouter().execute("/status", _context(session=ToolSession()))

    assert "Recent tools:" in result.text
    assert "bash ok 01:02:03 | exit 0" in result.text
    assert "read_file failed (FileNotFoundError) 01:03:04 | stdout 1.2k chars" in result.text


@pytest.mark.asyncio
async def test_status_ignores_unavailable_tool_records() -> None:
    class FailingToolSession(FakeSession):
        async def get_tool_records(self, limit=None, call_ids=None):
            raise RuntimeError("store unavailable")

    result = await SlashCommandRouter().execute("/status", _context(session=FailingToolSession()))

    assert "Status:" in result.text
    assert "Recent tools:" not in result.text


@pytest.mark.asyncio
async def test_config_does_not_leak_api_key(monkeypatch) -> None:
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "secret-value")
    monkeypatch.setattr(Config, "OPENAI_API_BASE", "https://example.com/v1")
    monkeypatch.setattr(Config, "DEFAULT_MODEL", "test-model")
    monkeypatch.setattr(Config, "MODEL_REASONING_EFFORT", "xhigh")
    monkeypatch.setattr(Config, "SETTINGS_PATH", r"C:\Users\admin\.chainpeer\settings.json")
    monkeypatch.setattr(Config, "SETTINGS_EXISTS", True)

    result = await SlashCommandRouter().execute("/config", _context())

    assert "apiKey: set" in result.text
    assert "baseUrl: https://example.com/v1" in result.text
    assert "model: test-model" in result.text
    assert "secret-value" not in result.text


@pytest.mark.asyncio
async def test_doctor_reports_setup_without_leaking_api_key(monkeypatch, tmp_path) -> None:
    class SessionWithRoot(FakeSession):
        _session_root = tmp_path / "sessions"

    monkeypatch.setattr(Config, "OPENAI_API_KEY", "secret-value")
    monkeypatch.setattr(Config, "OPENAI_API_BASE", "https://example.com/v1")
    monkeypatch.setattr(Config, "DEFAULT_MODEL", "test-model")
    monkeypatch.setattr(Config, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(Config, "SETTINGS_EXISTS", True)
    monkeypatch.setattr(Config, "CONTEXT_WINDOW_TOKENS", 100000)
    monkeypatch.setattr(Config, "EFFECTIVE_CONTEXT_WINDOW_PERCENT", 90)

    result = await SlashCommandRouter().execute("/doctor", _context(session=SessionWithRoot()))

    assert "Doctor:" in result.text
    assert "API key: set" in result.text
    assert "Model: test-model" in result.text
    assert "Session store:" in result.text
    assert "secret-value" not in result.text


@pytest.mark.asyncio
async def test_doctor_rejects_extra_args() -> None:
    result = await SlashCommandRouter().execute("/doctor now", _context())

    assert result.text == "Usage: /doctor"


@pytest.mark.asyncio
async def test_model_set_updates_settings_and_active_runtime(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"model": "model_a", "apiKey": "secret-value"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHAINPEER_SETTINGS_PATH", str(path))
    Config.reload()
    runtime = FakeRuntime()
    context = SlashCommandContext(runtime=runtime, session=FakeSession(), debug=True)

    result = await SlashCommandRouter().execute("/model set model_b", context)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert "Model updated." in result.text
    assert "previous default: model_a" in result.text
    assert "new default: model_b" in result.text
    assert "active session: updated" in result.text
    assert data["model"] == "model_b"
    assert data["apiKey"] == "secret-value"
    assert Config.DEFAULT_MODEL == "model_b"
    assert runtime.model == "model_b"
    assert "secret-value" not in result.text


@pytest.mark.asyncio
async def test_model_rejects_invalid_set_args() -> None:
    result = await SlashCommandRouter().execute("/model set", _context())

    assert result.text == "Usage: /model or /model set <model>"


@pytest.mark.asyncio
async def test_compact_calls_session_compact_context() -> None:
    session = FakeSession()
    runtime = FakeRuntime()
    context = SlashCommandContext(runtime=runtime, session=session, debug=True)
    result = await SlashCommandRouter().execute("/compact", context)

    assert runtime.compact_called is True
    assert session.compact_called is False
    assert "Compact complete." in result.text
    assert "runtime_compact_1" in result.text
    assert "tool calls: 0" in result.text


@pytest.mark.asyncio
async def test_exit_requests_cli_exit() -> None:
    result = await SlashCommandRouter().execute("/exit", _context())

    assert result.should_exit is True


@pytest.mark.asyncio
async def test_clear_requests_screen_clear() -> None:
    result = await SlashCommandRouter().execute("/clear", _context())

    assert result.clear_screen is True
    assert result.should_exit is False
    assert result.text == ""


@pytest.mark.asyncio
async def test_clear_rejects_extra_args() -> None:
    result = await SlashCommandRouter().execute("/clear now", _context())

    assert result.clear_screen is False
    assert result.text == "Usage: /clear"


@pytest.mark.asyncio
async def test_draft_shows_saved_input_draft(tmp_path) -> None:
    class DraftSession(FakeSession):
        _session_paths = {"base": str(tmp_path / "session_1")}

    base = tmp_path / "session_1"
    base.mkdir()
    (base / "input_draft.txt").write_text("continue this prompt", encoding="utf-8")

    result = await SlashCommandRouter().execute("/draft", _context(session=DraftSession()))

    assert "Saved input draft:" in result.text
    assert "input_draft.txt" in result.text
    assert "continue this prompt" in result.text


@pytest.mark.asyncio
async def test_draft_reports_missing_draft(tmp_path) -> None:
    class DraftSession(FakeSession):
        _session_paths = {"base": str(tmp_path / "session_1")}

    result = await SlashCommandRouter().execute("/draft", _context(session=DraftSession()))

    assert result.text == "No saved input draft."


@pytest.mark.asyncio
async def test_draft_rejects_extra_args() -> None:
    result = await SlashCommandRouter().execute("/draft clear", _context())

    assert result.text == "Usage: /draft"


@pytest.mark.asyncio
async def test_skill_lists_project_skill(tmp_path, monkeypatch) -> None:
    skill_dir = tmp_path / ".chainpeer" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\ntriggers: []\n---\n\nBody\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = await SlashCommandRouter().execute("/skill", _context())

    assert "demo [project]" in result.text
    assert "Demo skill" in result.text


@pytest.mark.asyncio
async def test_plan_without_active_plan_is_clear(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_SESSION_ROOT", raising=False)
    monkeypatch.delenv("AGENT_SESSION_ID", raising=False)

    result = await SlashCommandRouter().execute("/plan", _context())

    assert result.text == "No active plan."


@pytest.mark.asyncio
async def test_chat_cli_slash_command_does_not_call_runtime() -> None:
    runtime = FakeRuntime()
    cli = ChatCLI(runtime=runtime, session=FakeSession())
    output = io.StringIO()

    with redirect_stdout(output):
        should_exit = await cli._run_slash_command_async("/help")

    assert should_exit is False
    assert runtime.called is False
    assert "Available commands" in output.getvalue()


@pytest.mark.asyncio
async def test_chat_cli_clear_command_clears_console_without_runtime() -> None:
    runtime = FakeRuntime()
    cli = ChatCLI(runtime=runtime, session=FakeSession())
    called = []

    cli._console.clear = lambda: called.append(True)

    should_exit = await cli._run_slash_command_async("/clear")

    assert should_exit is False
    assert runtime.called is False
    assert called == [True]


@pytest.mark.asyncio
async def test_chat_cli_normal_turn_still_calls_runtime() -> None:
    runtime = FakeRuntime()
    cli = ChatCLI(runtime=runtime, session=FakeSession())

    await cli._run_turn_async("hello")

    assert runtime.called is True


def main() -> int:
    test_router_exposes_sorted_command_names()
    test_router_exposes_command_descriptions()
    asyncio.run(test_help_returns_command_list())
    asyncio.run(test_help_returns_command_specific_usage())
    asyncio.run(test_help_accepts_command_alias())
    asyncio.run(test_help_reports_unknown_command())
    asyncio.run(test_help_rejects_too_many_args())
    asyncio.run(test_unknown_command_returns_friendly_error())
    asyncio.run(test_status_shows_session_model_debug_and_message_count())
    asyncio.run(test_status_shows_latest_sampling_usage())
    asyncio.run(test_status_shows_recent_tool_summaries())
    asyncio.run(test_status_ignores_unavailable_tool_records())
    asyncio.run(test_model_rejects_invalid_set_args())
    asyncio.run(test_compact_calls_session_compact_context())
    asyncio.run(test_clear_requests_screen_clear())
    asyncio.run(test_clear_rejects_extra_args())
    asyncio.run(test_draft_rejects_extra_args())
    asyncio.run(test_exit_requests_cli_exit())
    asyncio.run(test_chat_cli_slash_command_does_not_call_runtime())
    asyncio.run(test_chat_cli_clear_command_clears_console_without_runtime())
    asyncio.run(test_chat_cli_normal_turn_still_calls_runtime())
    print("CLI slash command tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
