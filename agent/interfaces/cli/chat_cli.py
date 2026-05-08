"""Command-line interface adapter."""

from __future__ import annotations

import re
import sys

from agent.interfaces.cli.ui import print_rainbow_logo, render_markdown
from rich.console import Console
from rich.text import Text


class _StreamingRenderer:
    """Append-only renderer for a small markdown subset."""

    _INLINE_TOKEN_RE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*)")
    _PLAIN_TEXT_RE = re.compile(r"[`*#>|]")

    def __init__(self, console: Console):
        self._console = console
        self._pending = ""
        self._in_code_block = False
        self._line_open = False
        self._last_output_target = "stdout"

    def append(self, text: str) -> None:
        self._pending += text
        while True:
            newline_index = self._pending.find("\n")
            if newline_index == -1:
                break
            line = self._pending[:newline_index]
            self._pending = self._pending[newline_index + 1 :]
            self._render_line(line, newline=True)
        self._flush_pending_plain_text()
        
    def show_retry(self, attempt: int, exception: Exception) -> None:
        self.flush()
        msg = f"⚠️ API 繁忙或出现网络异常 ({type(exception).__name__})，正在进行第 {attempt}/5 次重试 (按 Ctrl+C 可中断)..."
        self._console.print(msg, style="bold yellow")
        self._last_output_target = "console"

    def flush(self) -> None:
        if not self._pending:
            return
        self._render_line(self._pending, newline=False)
        self._pending = ""

    def finish_message(self) -> None:
        if self._pending:
            self._render_line(self._pending, newline=False)
            self._pending = ""
        if not self._line_open:
            return
        self._write_message_boundary_newline()
        self._line_open = False

    def _flush_pending_plain_text(self) -> None:
        if not self._pending or self._in_code_block:
            return
        if not self._is_plain_line(self._pending):
            return
        self._write_plain(self._pending, newline=False)
        self._pending = ""

    def _render_line(self, line: str, *, newline: bool) -> None:
        if self._is_table_line(line):
            self._render_table_line(line, newline=newline)
            return

        if line.strip().startswith("```"):
            self._in_code_block = not self._in_code_block
            return

        if self._in_code_block:
            renderable = Text(line, style="cyan")
        else:
            if self._is_plain_line(line):
                self._write_plain(line, newline=newline)
                return
            renderable = self._render_markdownish_line(line)
        self._print_console(renderable, newline=newline)

    def _is_plain_line(self, line: str) -> bool:
        if not line:
            return True
        if self._PLAIN_TEXT_RE.search(line):
            return False
        stripped = line.lstrip()
        if stripped.startswith(("-", "*", "+")):
            return False
        if re.match(r"^\d+\.\s+", stripped):
            return False
        return True

    def _write_plain(self, text: str, *, newline: bool) -> None:
        sys.stdout.write(text)
        if newline:
            sys.stdout.write("\n")
        self._line_open = bool(text) and not newline
        if newline:
            self._line_open = False
        self._last_output_target = "stdout"
        sys.stdout.flush()

    def _print_console(self, renderable, *, newline: bool) -> None:
        self._console.print(renderable, end="\n" if newline else "", soft_wrap=True, highlight=False)
        if newline:
            self._line_open = False
        else:
            plain = getattr(renderable, "plain", "")
            if plain:
                self._line_open = True
        self._last_output_target = "console"

    def _write_message_boundary_newline(self) -> None:
        if self._last_output_target == "console":
            self._console.print("", end="\n", soft_wrap=True, highlight=False)
            return
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _render_table_line(self, line: str, *, newline: bool) -> None:
        if self._is_table_separator(line):
            return

        cells = self._parse_table_row(line)
        if not cells:
            return

        output = Text()
        for index, cell in enumerate(cells):
            if index > 0:
                output.append(" | ", style="dim")
            output.append_text(self._render_inline(cell, base_style="bold cyan" if index == 0 else ""))
        self._print_console(output, newline=newline)

    def _is_table_line(self, line: str) -> bool:
        stripped = line.strip()
        if self._in_code_block or not stripped:
            return False
        if "|" not in stripped:
            return False
        if stripped.count("|") < 2:
            return False
        return stripped.startswith("|") or stripped.endswith("|")

    def _is_table_separator(self, line: str) -> bool:
        cells = self._parse_table_row(line)
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)

    def _parse_table_row(self, line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

    def _render_markdownish_line(self, line: str) -> Text:
        if not line:
            return Text("")

        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            level = len(heading_match.group(1))
            style = "bold bright_white" if level <= 2 else "bold cyan"
            return self._render_inline(heading_match.group(2), base_style=style)

        quote_match = re.match(r"^(\s*)>\s?(.*)$", line)
        if quote_match:
            text = Text(quote_match.group(1))
            text.append("│ ", style="dim green")
            text.append_text(self._render_inline(quote_match.group(2), base_style="green"))
            return text

        list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if list_match:
            text = Text(list_match.group(1))
            text.append(f"{list_match.group(2)} ", style="bold yellow")
            text.append_text(self._render_inline(list_match.group(3)))
            return text

        return self._render_inline(line)

    def _render_inline(self, text: str, base_style: str = "") -> Text:
        if "`" not in text and "**" not in text:
            return Text(text, style=base_style)

        output = Text(style=base_style)
        cursor = 0
        for match in self._INLINE_TOKEN_RE.finditer(text):
            if match.start() > cursor:
                output.append(text[cursor:match.start()], style=base_style)
            token = match.group(0)
            if token.startswith("`") and token.endswith("`"):
                output.append(token[1:-1], style="bold cyan")
            elif token.startswith("**") and token.endswith("**"):
                output.append(token[2:-2], style=f"{base_style} bold".strip())
            else:
                output.append(token, style=base_style)
            cursor = match.end()
        if cursor < len(text):
            output.append(text[cursor:], style=base_style)
        return output


class ChatCLI:
    """Interactive CLI that delegates core behavior to application runtime."""

    def __init__(self, runtime, session, debug: bool = False):
        self._runtime = runtime
        self._session = session
        self._debug = debug
        self._assistant_buffer: list[str] = []
        self._console = Console()
        self._streaming_renderer = _StreamingRenderer(self._console)

    def start(self) -> None:
        self._render_banner()
        try:
            self._session.ensure_session()
        except Exception as exc:
            print(str(exc))
            return

        self._session.initialize_history()
        self._render_loaded_messages()
        self._loop()

    def _render_banner(self) -> None:
        print_rainbow_logo()
        if self._debug:
            print("Chain Peer v0.1 (Debug Mode: True) 输入 'quit' 退出")
        else:
            print("Chain Peer v0.1")
            print("Welcome back!")
        print("-" * 50)

    def _render_loaded_messages(self) -> None:
        if not self._session.loaded_existing:
            return
        print("\n[历史会话]")
        for message in self._session.get_messages_slice():
            role = message.get("role")
            content = message.get("content", "")
            if role in {"assistant", "user"} and isinstance(content, str) and content.strip():
                print(f"\n{role}:")
                render_markdown(content)

    def _loop(self) -> None:
        # Connect the retry callback
        if hasattr(self._runtime._chat_client, 'on_retry'):
            self._runtime._chat_client.on_retry = self._on_retry
            
        while True:
            try:
                user_input = input("\n> ").strip()
            except KeyboardInterrupt:
                print("\n再见！👋")
                break

            if user_input.lower() in {"quit", "exit", "q"}:
                print("再见！👋")
                break
            if not user_input:
                continue

            print("\nAgent:")
            self._assistant_buffer = []
            self._streaming_renderer = _StreamingRenderer(self._console)
            self._session.persist_message("user", user_input)

            try:
                self._runtime.process_user_turn(
                    session=self._session,
                    on_content=self._on_content,
                    on_debug=self._on_debug if self._debug else None,
                    on_assistant_message_complete=self._on_assistant_message_complete,
                )
                self._streaming_renderer.flush()
                print()
            except KeyboardInterrupt:
                self._streaming_renderer.flush()
                print("\n[User Interrupted: Session state preserved. You can resume later.]")
            except Exception as exc:
                self._streaming_renderer.flush()
                print(f"\nError: {exc}")

    def _on_content(self, text: str) -> None:
        self._assistant_buffer.append(text)
        self._streaming_renderer.append(text)
        
    def _on_retry(self, attempt: int, exception: Exception) -> None:
        self._streaming_renderer.show_retry(attempt, exception)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")

    def _on_assistant_message_complete(self) -> None:
        self._streaming_renderer.finish_message()

