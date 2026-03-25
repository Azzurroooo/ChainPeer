"""Command-line interface adapter."""

from __future__ import annotations

from agent.interfaces.cli.ui import markdown_renderable, print_rainbow_logo, render_markdown
from rich.console import Console
from rich.live import Live
from rich.text import Text


class ChatCLI:
    """Interactive CLI that delegates core behavior to application runtime."""

    def __init__(self, runtime, session, debug: bool = False):
        self._runtime = runtime
        self._session = session
        self._debug = debug
        self.chat_history: list[dict] = []
        self._assistant_buffer: list[str] = []
        self._console = Console()
        self._live: Live | None = None

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
            self.chat_history.append({"role": "user", "content": user_input})
            self._session.persist_message("user", user_input)

            try:
                with Live(
                    Text(""),
                    console=self._console,
                    refresh_per_second=12,
                    transient=True,
                    vertical_overflow="visible",
                ) as live:
                    self._live = live
                    self._runtime.process_user_turn(
                        chat_history=self.chat_history,
                        session=self._session,
                        on_content=self._on_content,
                        on_debug=self._on_debug if self._debug else None,
                    )
                assistant_text = "".join(self._assistant_buffer).strip()
                if assistant_text:
                    render_markdown(assistant_text)
                print()
            except Exception as exc:
                print(f"\nError: {exc}")
            finally:
                self._live = None

    def _on_content(self, text: str) -> None:
        self._assistant_buffer.append(text)
        if not self._live:
            return
        snapshot = "".join(self._assistant_buffer)
        if snapshot.strip():
            self._live.update(markdown_renderable(snapshot), refresh=True)
        else:
            self._live.update(Text(snapshot), refresh=True)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")
