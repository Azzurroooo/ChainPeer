"""Command-line interface adapter."""

from __future__ import annotations

import asyncio

from agent.application.runtime.cancellation import CancellationTokenSource
from agent.domain.events import (
    RuntimeEvent,
    ToolCallStartedEvent,
    ToolProgressEvent,
    ToolResultEvent,
    TurnStartedEvent,
    ToolBatchStartedEvent,
    PlanSnapshotEvent,
    DataIntegrityWarningEvent,
)
from agent.interfaces.cli.ui import print_rainbow_logo, render_markdown, StreamingRenderer
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
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
        self._prompt_session: PromptSession | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._current_cancel_source: CancellationTokenSource | None = None

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
                self._shutdown_loop(loop)
            finally:
                if not loop.is_closed():
                    loop.close()
                self._event_loop = None

    def _render_banner(self) -> None:
        print_rainbow_logo()
        if self._debug:
            print("Quanora v0.1 (Debug Mode: True) 输入 'quit' 退出")
        else:
            print("Quanora v0.1")
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
                user_input = self._read_user_input()
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
                if self._current_cancel_source:
                    self._current_cancel_source.cancel("User interrupted")
                self._streaming_renderer.flush()
                print("\n[User Interrupted: Session state preserved. You can resume later.]")
            except Exception as exc:
                self._streaming_renderer.flush()
                print(f"\nError: {exc}")

    def _read_user_input(self) -> str:
        if self._prompt_session is None:
            self._prompt_session = PromptSession(key_bindings=self._build_input_key_bindings(), multiline=True)
        return self._prompt_session.prompt("\n> ").strip()

    def _build_input_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("c-m")
        def _(event):
            event.app.exit(result=event.app.current_buffer.text)

        @bindings.add("c-j")
        def _(event):
            event.app.current_buffer.insert_text("\n")

        for sequence in (
            ("escape", "c-m"),
            ("escape", "c-j"),
            ("escape", "[", "1", "3", ";", "2", "u"),
            ("escape", "[", "1", "3", ";", "2", "~"),
        ):
            @bindings.add(*sequence)
            def _(event):
                event.app.current_buffer.insert_text("\n")

        return bindings

    async def _run_turn_async(self, user_input: str) -> None:
        cancel_source = CancellationTokenSource()
        self._current_cancel_source = cancel_source
        event_stream = self._runtime.run_turn(query=user_input, cancellation_token=cancel_source.token)
        try:
            async for event in event_stream:
                self._on_event(event)
        finally:
            self._current_cancel_source = None
            if not getattr(event_stream, "ag_running", False):
                aclose = getattr(event_stream, "aclose", None)
                if callable(aclose):
                    await aclose()

    def _shutdown_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if loop.is_closed():
            return
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
            
    def _on_event(self, event: RuntimeEvent) -> None:
        from agent.domain.events import (
            AssistantDeltaEvent,
            AssistantMessageCompletedEvent,
            SkillActivatedEvent,
            ToolCallStartedEvent,
            ToolProgressEvent,
            ToolResultEvent,
            TurnFailedEvent,
            TurnCancelledEvent,
            TurnStartedEvent,
            ToolBatchStartedEvent,
            PlanSnapshotEvent,
            DataIntegrityWarningEvent,
        )

        if isinstance(event, TurnStartedEvent):
            # Early "thinking" indicator so the user never sees a silent gap.
            self._console.print("[dim]🤔 思考中…[/dim]")
        elif isinstance(event, AssistantDeltaEvent):
            self._assistant_buffer.append(event.text)
            self._streaming_renderer.append(event.text)
        elif isinstance(event, AssistantMessageCompletedEvent):
            self._streaming_renderer.finish_message()
        elif isinstance(event, SkillActivatedEvent):
            self._console.print(
                f"[dim italic]🧩 技能启用: {getattr(event, 'skill_name', 'unknown')}"
                f" ({getattr(event, 'reason', '') or 'auto'})[/dim italic]"
            )
        elif isinstance(event, ToolBatchStartedEvent):
            # Flush any pending streaming text BEFORE the tool panel so the
            # batch announcement appears below the assistant's narration.
            self._streaming_renderer.flush()
            count = getattr(event, "count", 0)
            names = getattr(event, "tool_names", []) or []
            # Compact: list distinct names with counts (e.g. "bash×2, read_file")
            from collections import Counter
            tally = Counter(names)
            summary = ", ".join(f"{n}×{c}" if c > 1 else n for n, c in tally.items())
            self._console.print(f"[cyan]▶ 即将执行 {count} 个工具: {summary}[/cyan]")
        elif isinstance(event, ToolCallStartedEvent):
            self._streaming_renderer.flush()
            preview = getattr(event, "args_preview", "") or ""
            tool_name = getattr(event, "tool_name", "unknown")
            line = f"[cyan]  🔧 {tool_name}[/cyan]"
            self._console.print(line)
            if preview:
                # Indent under the tool name; truncate to terminal-friendly width.
                self._console.print(f"[dim]     └─ {preview}[/dim]")
        elif isinstance(event, ToolProgressEvent):
            pass  # We let tool output print via bash thread for now
        elif isinstance(event, ToolResultEvent):
            status = getattr(event, "status", "unknown")
            summary = getattr(event, "summary", "") or ""
            duration_ms = getattr(event, "duration_ms", 0)
            duration_part = f" ({duration_ms}ms)" if duration_ms else ""
            if status == "ok":
                icon = "✅"
                color = "green"
            elif status == "error":
                icon = "❌"
                color = "red"
            else:
                icon = "•"
                color = "dim"
            tool_name = getattr(event, "tool_name", "unknown")
            line = f"[{color}]     {icon} {tool_name}{duration_part}"
            if summary:
                line += f" — {summary}"
            line += f"[/{color}]"
            self._console.print(line)
        elif isinstance(event, PlanSnapshotEvent):
            # Render a compact one-block plan panel: counts + current focus.
            title = getattr(event, "title", "") or "(plan)"
            total = getattr(event, "total_steps", 0)
            done = getattr(event, "completed_steps", 0)
            ip = getattr(event, "in_progress_steps", 0)
            blocked = getattr(event, "blocked_steps", 0)
            focus = getattr(event, "current_focus", "") or "—"
            self._console.print(
                f"[magenta]📋 计划[/magenta] [bold]{title}[/bold]"
                f"  [green]✅ {done}/{total}[/green]"
                f"  [yellow]🔄 {ip}[/yellow]"
                + (f"  [red]🚫 {blocked}[/red]" if blocked else "")
                + f"   focus: [italic]{focus}[/italic]"
            )
        elif isinstance(event, DataIntegrityWarningEvent):
            # Loud, persistent banner — the agent is FORBIDDEN to fabricate
            # data, so we surface the source failure clearly to the user.
            tool_name = getattr(event, "tool_name", "?")
            reason = getattr(event, "reason", "data source failed")
            action = getattr(event, "suggested_action", "")
            self._console.print(
                "\n[bold red on yellow] ⚠ 数据完整性警告 [/bold red on yellow]"
                f" [yellow]{tool_name} 失败,Quanora 不会编造缺失数据[/yellow]"
            )
            self._console.print(f"[red]    原因: {reason}[/red]")
            if action:
                self._console.print(f"[yellow]    建议: {action}[/yellow]")
        elif isinstance(event, TurnFailedEvent):
            self._streaming_renderer.flush()
            message = getattr(event, "error", "") or getattr(event, "reason", "") or "unknown"
            print(f"\n[Error] Turn failed: {message}")
        elif isinstance(event, TurnCancelledEvent):
            self._streaming_renderer.flush()
            print(f"\n[Cancelled] Turn cancelled: {getattr(event, 'reason', 'unknown')}")

    def _on_retry(self, attempt: int, exception: Exception) -> None:
        self._streaming_renderer.show_retry(attempt, exception)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")
