"""Command-line interface adapter."""

from __future__ import annotations

import asyncio

from agent.domain.events import RuntimeEvent, ToolCallStartedEvent, ToolProgressEvent, ToolResultEvent
from agent.interfaces.cli.ui import print_rainbow_logo, render_markdown, StreamingRenderer
from rich.console import Console


class ChatCLI:
    """Interactive CLI that delegates core behavior to application runtime."""

    def __init__(self, runtime, session, debug: bool = False):
        self._runtime = runtime
        self._session = session
        self._debug = debug
        self._assistant_buffer: list[str] = []
        self._console = Console()
        self._streaming_renderer = StreamingRenderer(self._console)
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self._render_banner()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._event_loop = loop

        try:
            async def _init_session():
                try:
                    await self._session.initialize()
                except Exception as exc:
                    print(str(exc))
                    return False
                return True

            if not loop.run_until_complete(_init_session()):
                return

            self._render_loaded_messages()
            self._loop()
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except KeyboardInterrupt:
                pass
            loop.close()
            self._event_loop = None

    def _render_banner(self) -> None:
        print_rainbow_logo()
        if self._debug:
            print("Chain Peer v0.1 (Debug Mode: True) 输入 'quit' 退出")
        else:
            print("Chain Peer v0.1")
            print("Welcome back!")
        print("-" * 50)

    def _render_loaded_messages(self) -> None:
        messages = self._event_loop.run_until_complete(self._session.get_messages_slice())
        if len(messages) <= 1:
            return
            
        print("\n[历史会话]")
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role in ("user", "assistant") and content:
                print(f"\n{role}:")
                render_markdown(content)

    def _loop(self) -> None:
        if hasattr(self._runtime, "set_retry_callback"):
            self._runtime.set_retry_callback(self._on_retry)
            
        while True:
            try:
                user_input = input("\n> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n再见！👋")
                break

            if user_input.lower() in {"quit", "exit", "q"}:
                print("再见！👋")
                break
            if not user_input:
                continue

            print("\nAgent:")
            self._assistant_buffer = []
            self._streaming_renderer = StreamingRenderer(self._console)

            try:
                self._event_loop.run_until_complete(self._run_turn_async(user_input))
                self._streaming_renderer.flush()
                print()
            except KeyboardInterrupt:
                self._streaming_renderer.flush()
                print("\n[User Interrupted: Session state preserved. You can resume later.]")
            except Exception as exc:
                self._streaming_renderer.flush()
                print(f"\nError: {exc}")

    async def _run_turn_async(self, user_input: str) -> None:
        # Pass user_input directly to the runtime facade
        async for event in self._runtime.run_turn(query=user_input):
            self._on_event(event)
            
    def _on_event(self, event: RuntimeEvent) -> None:
        from agent.domain.events import AssistantDeltaEvent, AssistantMessageCompletedEvent, ToolCallStartedEvent, ToolProgressEvent, ToolResultEvent, TurnFailedEvent, TurnCancelledEvent
        
        if isinstance(event, AssistantDeltaEvent):
            self._assistant_buffer.append(event.text)
            self._streaming_renderer.append(event.text)
        elif isinstance(event, AssistantMessageCompletedEvent):
            self._streaming_renderer.finish_message()
        elif isinstance(event, ToolCallStartedEvent):
            self._console.print(f"[dim italic]🚀 任务启动: {getattr(event, 'tool_name', 'unknown')} (ID: {getattr(event, 'tool_call_id', 'unknown')})[/dim italic]")
        elif isinstance(event, ToolProgressEvent):
            pass # We let tool output print via bash thread for now
        elif isinstance(event, ToolResultEvent):
            self._console.print(f"[dim italic]✅ 任务完成: {getattr(event, 'tool_name', 'unknown')}[/dim italic]")
        elif isinstance(event, TurnFailedEvent):
            self._streaming_renderer.flush()
            print(f"\n[Error] Turn failed: {getattr(event, 'reason', 'unknown')}")
        elif isinstance(event, TurnCancelledEvent):
            self._streaming_renderer.flush()
            print(f"\n[Cancelled] Turn cancelled: {getattr(event, 'reason', 'unknown')}")

    def _on_retry(self, attempt: int, exception: Exception) -> None:
        self._streaming_renderer.show_retry(attempt, exception)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")

