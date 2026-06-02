import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.interfaces.cli.ui.prompt_chrome import prompt_continuation, prompt_message, prompt_toolbar


class FakeSession:
    session_id = "20260602_123456_abcdef12"
    model = "very-long-model-name-that-will-not-fit-cleanly"


def test_prompt_message_names_speaker() -> None:
    assert prompt_message() == "\nYou > "


def test_prompt_continuation_marks_multiline_input() -> None:
    assert prompt_continuation(0, 2, False) == "  ... "


def test_prompt_toolbar_includes_status_and_shortcuts(tmp_path) -> None:
    text = prompt_toolbar(
        FakeSession(),
        debug=True,
        cwd=tmp_path / "workspace",
        usage={"context_usage_percent": 0.42, "cache_hit_rate": 0.812},
    )

    assert "session 20260602...ef12" in text
    assert "model very-long-model-name-th..." in text
    assert "ctx 42.0% cache 81.2%" in text
    assert "cwd workspace" in text
    assert "debug on" in text
    assert "Enter send" in text
    assert "Ctrl+J newline" in text
    assert "Tab complete /commands" in text
    assert "Right accept hint" in text
    assert "Ctrl+C interrupt" in text


def test_prompt_toolbar_handles_missing_session_values(tmp_path) -> None:
    text = prompt_toolbar(object(), cwd=tmp_path)

    assert "session unknown" in text
    assert "model unknown" in text


def test_prompt_toolbar_falls_back_to_token_counts(tmp_path) -> None:
    text = prompt_toolbar(
        FakeSession(),
        cwd=tmp_path,
        usage={"input_tokens": 121300, "effective_context_window_tokens": 245480},
    )

    assert "ctx 121.3k/245.5k" in text


def main() -> int:
    test_prompt_message_names_speaker()
    test_prompt_continuation_marks_multiline_input()
    test_prompt_toolbar_includes_status_and_shortcuts(Path.cwd())
    test_prompt_toolbar_handles_missing_session_values(Path.cwd())
    test_prompt_toolbar_falls_back_to_token_counts(Path.cwd())
    print("Prompt chrome tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
