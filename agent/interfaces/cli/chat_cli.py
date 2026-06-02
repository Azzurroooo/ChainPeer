"""Command-line interface adapter."""

from __future__ import annotations

import asyncio

from agent.application.runtime.cancellation import CancellationTokenSource
from agent.domain.events import RuntimeEvent
from agent.interfaces.cli.commands.completer import SlashCommandCompleter
from agent.interfaces.cli.commands import SlashCommandContext, SlashCommandRouter
from agent.interfaces.cli.status import CliStatusRenderer
from agent.interfaces.cli.ui import (
    print_rainbow_logo,
    prompt_continuation,
    prompt_message,
    prompt_toolbar,
    render_markdown,
    render_resume_preview,
    StreamingRenderer,
)
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import InMemoryHistory
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
        self._status_renderer = CliStatusRenderer(
            self._console,
            debug=debug,
            before_print=self._flush_assistant_for_status,
        )
        self._prompt_session: PromptSession | None = None
        self._input_history = InMemoryHistory()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._current_cancel_source: CancellationTokenSource | None = None
        self._latest_usage: dict[str, object] | None = None
        self._slash_router = SlashCommandRouter()
        self._slash_completer = SlashCommandCompleter(self._slash_router.command_infos())

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

            loop.run_until_complete(self._load_latest_usage_async())
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
            print("Chain Peer v0.1 (Debug Mode: True)")
        else:
            print("Chain Peer v0.1")
        print("Type /help for commands. Enter sends, Ctrl+J adds a newline.")
        print("-" * 50)

    def _render_loaded_messages(self) -> None:
        messages = self._event_loop.run_until_complete(self._session.get_messages_slice())
        self._seed_input_history(messages)
        preview = render_resume_preview(messages, session_id=getattr(self._session, "session_id", None))
        if not preview:
            return
        print()
        self._console.print(preview, style="dim", highlight=False, markup=False)

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
            if self._is_slash_command(user_input):
                should_exit = self._event_loop.run_until_complete(self._run_slash_command_async(user_input))
                if should_exit:
                    break
                continue

            print("\nAgent:")
            self._assistant_buffer = []
            self._streaming_renderer = StreamingRenderer(self._console)
            self._status_renderer = CliStatusRenderer(
                self._console,
                debug=self._debug,
                before_print=self._flush_assistant_for_status,
            )

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
            self._prompt_session = PromptSession(
                key_bindings=self._build_input_key_bindings(),
                multiline=True,
                completer=self._slash_completer,
                complete_while_typing=True,
                history=self._input_history,
                auto_suggest=AutoSuggestFromHistory(),
                prompt_continuation=prompt_continuation,
                bottom_toolbar=lambda: prompt_toolbar(
                    self._session,
                    debug=self._debug,
                    usage=self._latest_usage,
                ),
            )
        return self._prompt_session.prompt(prompt_message()).strip()

    def _seed_input_history(self, messages: list[dict]) -> None:
        seen = set()
        for message in messages[-40:]:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = str(message.get("content") or "").strip()
            if not content or content in seen:
                continue
            self._input_history.append_string(content)
            seen.add(content)

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

    def _is_slash_command(self, text: str) -> bool:
        return text.lstrip().startswith("/")

    async def _run_slash_command_async(self, user_input: str) -> bool:
        result = await self._slash_router.execute(
            user_input,
            SlashCommandContext(runtime=self._runtime, session=self._session, debug=self._debug),
        )
        if result.clear_screen:
            self._console.clear()
        if result.text:
            render_markdown(result.text)
        return result.should_exit

    async def _load_latest_usage_async(self) -> None:
        get_usage = getattr(self._session, "get_latest_sampling_usage", None)
        if not callable(get_usage):
            return
        try:
            usage = await get_usage()
        except Exception:
            return
        self._latest_usage = dict(usage) if isinstance(usage, dict) else None

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

    def _flush_assistant_for_status(self) -> None:
        self._streaming_renderer.finish_message()
            
    def _on_event(self, event: RuntimeEvent) -> None:
        from agent.domain.events import (
            AssistantDeltaEvent,
            AssistantMessageCompletedEvent,
            TokenStatsUpdatedEvent,
        )
        
        if isinstance(event, AssistantDeltaEvent):
            self._assistant_buffer.append(event.text)
            self._streaming_renderer.append(event.text)
        elif isinstance(event, AssistantMessageCompletedEvent):
            self._streaming_renderer.finish_message()
        elif isinstance(event, TokenStatsUpdatedEvent):
            self._latest_usage = dict(event.stats) if isinstance(event.stats, dict) else None
            self._status_renderer.handle(event)
        else:
            self._status_renderer.handle(event)

    def _on_retry(self, attempt: int, exception: Exception) -> None:
        self._streaming_renderer.show_retry(attempt, exception)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")
