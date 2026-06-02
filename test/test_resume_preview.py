import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.interfaces.cli.ui.resume_preview import render_resume_preview


def test_resume_preview_shows_last_messages_and_hides_older_content() -> None:
    messages = [{"role": "system", "content": "sys"}]
    for index in range(8):
        messages.append({"role": "user", "content": f"question {index}"})

    text = render_resume_preview(messages, session_id="20260602_123456_abcdef12", limit=3)

    assert "Resumed session 20260602_1...ef12" in text
    assert "8 visible message(s), showing last 3" in text
    assert "5 older message(s) are hidden" in text
    assert "question 7" in text
    assert "question 0" not in text


def test_resume_preview_compacts_whitespace_and_truncates_content() -> None:
    text = render_resume_preview(
        [{"role": "assistant", "content": "hello\n\n" + ("x" * 80)}],
        preview_chars=24,
    )

    assert "assistant: hello xxxxxxxxxxxxxxx..." in text
    assert "\n\nhello" not in text


def test_resume_preview_returns_empty_for_no_visible_messages() -> None:
    assert render_resume_preview([{"role": "system", "content": "sys"}]) == ""


def main() -> int:
    test_resume_preview_shows_last_messages_and_hides_older_content()
    test_resume_preview_compacts_whitespace_and_truncates_content()
    test_resume_preview_returns_empty_for_no_visible_messages()
    print("Resume preview tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
