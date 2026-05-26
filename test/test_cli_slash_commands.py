import asyncio
import io
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
from agent.interfaces.cli.commands import SlashCommandContext, SlashCommandRouter


class FakeSession:
    session_id = "session_1"
    model = "model_a"

    async def get_messages_slice(self):
        return [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]


class FakeRuntime:
    def __init__(self):
        self.called = False

    def run_turn(self, query=None, cancellation_token=None):
        self.called = True
        return EmptyStream()


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
    assert "/skill" in result.text
    assert result.should_exit is False


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
async def test_config_does_not_leak_api_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")

    result = await SlashCommandRouter().execute("/config", _context())

    assert "OPENAI_API_KEY: set" in result.text
    assert "secret-value" not in result.text


@pytest.mark.asyncio
async def test_model_set_is_placeholder() -> None:
    result = await SlashCommandRouter().execute("/model set model_b", _context())

    assert "not implemented" in result.text


@pytest.mark.asyncio
async def test_exit_requests_cli_exit() -> None:
    result = await SlashCommandRouter().execute("/exit", _context())

    assert result.should_exit is True


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
async def test_chat_cli_normal_turn_still_calls_runtime() -> None:
    runtime = FakeRuntime()
    cli = ChatCLI(runtime=runtime, session=FakeSession())

    await cli._run_turn_async("hello")

    assert runtime.called is True


def main() -> int:
    asyncio.run(test_help_returns_command_list())
    asyncio.run(test_unknown_command_returns_friendly_error())
    asyncio.run(test_status_shows_session_model_debug_and_message_count())
    asyncio.run(test_model_set_is_placeholder())
    asyncio.run(test_exit_requests_cli_exit())
    asyncio.run(test_chat_cli_slash_command_does_not_call_runtime())
    asyncio.run(test_chat_cli_normal_turn_still_calls_runtime())
    print("CLI slash command tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
