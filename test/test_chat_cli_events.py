import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import InMemoryHistory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.domain.events import TokenStatsUpdatedEvent, ToolResultEvent, TurnFailedEvent
from agent.interfaces.cli.chat_cli import ChatCLI
from agent.interfaces.cli.ui import GitPromptStatus


def test_chat_cli_turn_failed_event_prints_error_field() -> None:
    cli = ChatCLI(runtime=None, session=None)
    output = io.StringIO()

    with redirect_stdout(output):
        cli._on_event(TurnFailedEvent(error="boom"))

    text = output.getvalue()
    if "boom" not in text:
        raise AssertionError(f"Expected CLI failure output to include error field, got: {text!r}")
    if "unknown" in text:
        raise AssertionError(f"Did not expect fallback output when error exists, got: {text!r}")


def test_chat_cli_tool_result_failed_uses_failed_status() -> None:
    cli = ChatCLI(runtime=None, session=None)
    output = io.StringIO()

    with redirect_stdout(output):
        cli._on_event(ToolResultEvent(tool_name="bash", status="failed"))

    text = output.getvalue()
    if "Tool: bash failed" not in text:
        raise AssertionError(f"Expected CLI to render failed tool status, got: {text!r}")


def test_chat_cli_banner_mentions_core_shortcuts() -> None:
    cli = ChatCLI(runtime=None, session=None)
    output = io.StringIO()

    with redirect_stdout(output):
        cli._render_banner()

    text = output.getvalue()
    if "Type /help" not in text or "Ctrl+J newline" not in text or "Ctrl+L clear" not in text:
        raise AssertionError(f"Expected banner shortcut hints, got: {text!r}")


def test_chat_cli_prompt_uses_status_toolbar(monkeypatch) -> None:
    captured = {}

    class FakeSession:
        session_id = "session_1234567890"
        model = "model_a"

    class FakePromptSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def prompt(self, message):
            captured["message"] = message
            captured["toolbar"] = captured["bottom_toolbar"]()
            captured["continuation"] = captured["prompt_continuation"](0, 2, False)
            return "hello"

    monkeypatch.setattr("agent.interfaces.cli.chat_cli.PromptSession", FakePromptSession)

    cli = ChatCLI(runtime=None, session=FakeSession(), debug=True)
    cli._git_status_provider.current = lambda: GitPromptStatus(branch="main", dirty=True)

    if cli._read_user_input() != "hello":
        raise AssertionError("Expected prompt result to be returned")
    if captured["message"] != "\nYou > ":
        raise AssertionError(f"Expected speaker prompt, got: {captured['message']!r}")
    if captured.get("completer") is None:
        raise AssertionError("Expected slash command completer")
    if captured.get("complete_while_typing") is not True:
        raise AssertionError("Expected completion while typing")
    if not isinstance(captured.get("history"), InMemoryHistory):
        raise AssertionError("Expected in-memory prompt history")
    if not isinstance(captured.get("auto_suggest"), AutoSuggestFromHistory):
        raise AssertionError("Expected history-based auto suggestions")
    if "session session_...7890" not in captured["toolbar"]:
        raise AssertionError(f"Expected session in toolbar, got: {captured['toolbar']!r}")
    if "model model_a" not in captured["toolbar"] or "debug on" not in captured["toolbar"]:
        raise AssertionError(f"Expected model/debug in toolbar, got: {captured['toolbar']!r}")
    if "git main*" not in captured["toolbar"]:
        raise AssertionError(f"Expected git status in toolbar, got: {captured['toolbar']!r}")
    if captured["continuation"] != "  ... ":
        raise AssertionError(f"Expected multiline continuation, got: {captured['continuation']!r}")


def test_chat_cli_prompt_toolbar_uses_latest_usage(monkeypatch) -> None:
    captured = {}

    class FakeSession:
        session_id = "session_1234567890"
        model = "model_a"

    class FakePromptSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def prompt(self, message):
            captured["toolbar"] = captured["bottom_toolbar"]()
            return "hello"

    monkeypatch.setattr("agent.interfaces.cli.chat_cli.PromptSession", FakePromptSession)

    cli = ChatCLI(runtime=None, session=FakeSession())
    cli._latest_usage = {"context_usage_percent": 0.5, "cache_hit_rate": 0.25}
    cli._read_user_input()

    if "ctx 50.0% cache 25.0%" not in captured["toolbar"]:
        raise AssertionError(f"Expected latest usage in toolbar, got: {captured['toolbar']!r}")


async def _load_latest_usage(cli: ChatCLI) -> None:
    await cli._load_latest_usage_async()


def test_chat_cli_loads_latest_usage_from_session() -> None:
    import asyncio

    class FakeSession:
        async def get_latest_sampling_usage(self):
            return {"context_usage_percent": 0.3}

    cli = ChatCLI(runtime=None, session=FakeSession())
    asyncio.run(_load_latest_usage(cli))

    if cli._latest_usage != {"context_usage_percent": 0.3}:
        raise AssertionError(f"Expected persisted usage to be loaded, got: {cli._latest_usage!r}")


def test_chat_cli_token_event_updates_latest_usage() -> None:
    cli = ChatCLI(runtime=None, session=None)
    output = io.StringIO()
    cli._console.file = output
    cli._status_renderer._console.file = output

    cli._on_event(TokenStatsUpdatedEvent(stats={"context_usage_percent": 0.5}))

    if cli._latest_usage != {"context_usage_percent": 0.5}:
        raise AssertionError(f"Expected token usage state to update, got: {cli._latest_usage!r}")
    if "Tokens:" not in output.getvalue():
        raise AssertionError(f"Expected token status to still render, got: {output.getvalue()!r}")


def test_chat_cli_loaded_messages_are_compact(monkeypatch) -> None:
    class FakeSession:
        session_id = "session_1234567890"

        async def get_messages_slice(self):
            messages = [{"role": "system", "content": "sys"}]
            messages.extend(
                {"role": "user", "content": f"old question {index} that should stay hidden"}
                for index in range(5)
            )
            messages.extend(
                [
                    {"role": "user", "content": "latest question"},
                    {"role": "assistant", "content": "latest answer"},
                ]
            )
            return messages

    class FakeLoop:
        def run_until_complete(self, awaitable):
            import asyncio

            return asyncio.run(awaitable)

    output = io.StringIO()
    cli = ChatCLI(runtime=None, session=FakeSession())
    cli._event_loop = FakeLoop()
    cli._console.file = output

    with redirect_stdout(output):
        cli._render_loaded_messages()

    text = output.getvalue()
    if "Resumed session session_1234567890" not in text:
        raise AssertionError(f"Expected compact resume header, got: {text!r}")
    if "latest question" not in text or "latest answer" not in text:
        raise AssertionError(f"Expected latest messages, got: {text!r}")
    if "old question 0" in text:
        raise AssertionError(f"Expected oldest messages to stay hidden, got: {text!r}")
    if "\nuser:\n" in text or "[历史会话]" in text:
        raise AssertionError(f"Expected old full transcript rendering to be gone, got: {text!r}")


def test_chat_cli_seeds_input_history_from_user_messages() -> None:
    cli = ChatCLI(runtime=None, session=None)
    cli._seed_input_history(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "first question"},
            {"role": "user", "content": "second question"},
        ]
    )

    history = list(cli._input_history.get_strings())
    if history != ["first question", "second question"]:
        raise AssertionError(f"Expected distinct user inputs in history, got: {history!r}")


def test_chat_cli_input_bindings_include_clear_shortcut() -> None:
    cli = ChatCLI(runtime=None, session=None)
    keys = {tuple(binding.keys) for binding in cli._build_input_key_bindings().bindings}

    if ("c-l",) not in keys:
        raise AssertionError(f"Expected Ctrl+L key binding, got: {keys!r}")


def test_chat_cli_clear_prompt_screen_clears_console() -> None:
    cli = ChatCLI(runtime=None, session=None)
    called = []
    cli._console.clear = lambda: called.append(True)

    cli._clear_prompt_screen()

    if called != [True]:
        raise AssertionError(f"Expected console.clear to be called once, got: {called!r}")


def main() -> int:
    test_chat_cli_turn_failed_event_prints_error_field()
    test_chat_cli_tool_result_failed_uses_failed_status()
    test_chat_cli_banner_mentions_core_shortcuts()
    test_chat_cli_loads_latest_usage_from_session()
    test_chat_cli_token_event_updates_latest_usage()
    test_chat_cli_seeds_input_history_from_user_messages()
    test_chat_cli_input_bindings_include_clear_shortcut()
    test_chat_cli_clear_prompt_screen_clears_console()
    print("ChatCLI event tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
