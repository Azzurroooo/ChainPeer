import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.domain.events import ToolResultEvent, TurnFailedEvent
from agent.interfaces.cli.chat_cli import ChatCLI


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

    if cli._read_user_input() != "hello":
        raise AssertionError("Expected prompt result to be returned")
    if captured["message"] != "\nYou > ":
        raise AssertionError(f"Expected speaker prompt, got: {captured['message']!r}")
    if "session session_...7890" not in captured["toolbar"]:
        raise AssertionError(f"Expected session in toolbar, got: {captured['toolbar']!r}")
    if "model model_a" not in captured["toolbar"] or "debug on" not in captured["toolbar"]:
        raise AssertionError(f"Expected model/debug in toolbar, got: {captured['toolbar']!r}")
    if captured["continuation"] != "  ... ":
        raise AssertionError(f"Expected multiline continuation, got: {captured['continuation']!r}")


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


def main() -> int:
    test_chat_cli_turn_failed_event_prints_error_field()
    test_chat_cli_tool_result_failed_uses_failed_status()
    print("ChatCLI event tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
