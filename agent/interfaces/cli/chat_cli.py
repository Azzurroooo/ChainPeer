"""Command-line interface adapter."""

from __future__ import annotations

import re

from agent.interfaces.cli.ui import print_rainbow_logo, render_markdown
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


class _StreamingRenderer:
    """Append-only renderer for a small markdown subset."""

    _INLINE_TOKEN_RE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*)")

    def __init__(self, console: Console):
        self._console = console
        self._pending = ""
        self._in_code_block = False
        self._table_lines: list[str] = []

    def append(self, text: str) -> None:
        self._pending += text
        while True:
            newline_index = self._pending.find("\n")
            if newline_index == -1:
                break
            line = self._pending[:newline_index]
            self._pending = self._pending[newline_index + 1 :]
            self._render_line(line, newline=True)

    def flush(self) -> None:
        self._flush_table()
        if not self._pending:
            return
        self._render_line(self._pending, newline=False)
        self._pending = ""

    def _render_line(self, line: str, *, newline: bool) -> None:
        if self._is_table_line(line):
            self._table_lines.append(line)
            return

        self._flush_table()

        if line.strip().startswith("```"):
            self._in_code_block = not self._in_code_block
            return

        if self._in_code_block:
            renderable = Text(line, style="cyan")
        else:
            renderable = self._render_markdownish_line(line)
        self._console.print(renderable, end="\n" if newline else "", soft_wrap=True, highlight=False)

    def _flush_table(self) -> None:
        if not self._table_lines:
            return

        parsed_rows = [self._parse_table_row(line) for line in self._table_lines if not self._is_table_separator(line)]
        self._table_lines = []
        if not parsed_rows:
            return

        column_count = max(len(row) for row in parsed_rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in parsed_rows]

        table = Table(box=box.SIMPLE_HEAVY, show_header=True, expand=False)
        for header in normalized_rows[0]:
            table.add_column(header=self._render_inline(header, base_style="bold cyan"))
        for row in normalized_rows[1:]:
            table.add_row(*[self._render_inline(cell) for cell in row])
        self._console.print(table, soft_wrap=True)

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
        self.chat_history: list[dict] = []
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
        self.chat_history = self._session.chat_history
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
        for message in self.chat_history:
            role = message.get("role")
            content = message.get("content", "")
            if role in {"assistant", "user"} and content:
                print(f"\n{role}:")
                render_markdown(content)

    def _loop(self) -> None:
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
            self.chat_history.append({"role": "user", "content": user_input})
            self._session.persist_message("user", user_input)

            try:
                self._runtime.process_user_turn(
                    chat_history=self.chat_history,
                    session=self._session,
                    on_content=self._on_content,
                    on_debug=self._on_debug if self._debug else None,
                )
                self._streaming_renderer.flush()
                print()
            except Exception as exc:
                self._streaming_renderer.flush()
                print(f"\nError: {exc}")

    def _on_content(self, text: str) -> None:
        self._assistant_buffer.append(text)
        self._streaming_renderer.append(text)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")
