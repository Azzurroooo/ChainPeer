"""JSONL stdio adapter for the headless ChainPeer runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from typing import Any

from agent.application.runtime.cancellation import CancellationTokenSource
from agent.bootstrap import build_basic_agent_dependencies
from agent.domain.events import UserQuestionRequestedEvent
from agent.infrastructure.config import Config
from agent.infrastructure.paths import validate_session_id
from agent.interfaces.cli.commands import SlashCommandContext, SlashCommandRouter
from agent.interfaces.cli.ui.resume_preview import render_resume_preview


class JsonlWriter:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def send(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def configure_stdio_server_signals() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class StdioRuntimeServer:
    def __init__(self, runtime, session, debug: bool = False):
        self._runtime = runtime
        self._session = session
        self._debug = debug
        self._slash_router = SlashCommandRouter()
        self._writer = JsonlWriter()
        self._requests: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._pending_answers: dict[str, asyncio.Future[str]] = {}
        self._current_cancel: CancellationTokenSource | None = None
        self._install_question_responder()

    async def run(self) -> int:
        reader = asyncio.create_task(self._read_stdin())
        try:
            return await self._serve()
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    def _install_question_responder(self) -> None:
        set_responder = getattr(self._runtime, "set_user_question_responder", None)
        if callable(set_responder):
            set_responder(self._answer_user_question)

    async def _serve(self) -> int:
        while True:
            request = await self._requests.get()
            if request is None:
                return 0
            method = str(request.get("method") or "")
            if method == "shutdown":
                await self._respond(request, {"ok": True})
                return 0
            await self._dispatch(request)

    async def _dispatch(self, request: dict[str, Any]) -> None:
        method = str(request.get("method") or "")
        try:
            if method == "initialize":
                await self._initialize(request)
            elif method == "turn.start":
                await self._run_turn(request)
            elif method == "compact":
                await self._compact(request)
            elif method == "model.set":
                await self._set_model(request)
            elif method == "slash.execute":
                await self._execute_slash(request)
            else:
                await self._respond_error(request, f"Unknown method: {method}", "MethodNotFound")
        except Exception as exc:
            await self._respond_error(request, str(exc), type(exc).__name__)

    async def _initialize(self, request: dict[str, Any]) -> None:
        await self._runtime.initialize()
        await self._respond(
            request,
            {
                "session_id": getattr(self._session, "session_id", None),
                "model": getattr(self._session, "model", None),
                "resume_preview": await self._resume_preview(),
                "slash_commands": self._slash_command_infos(),
            },
        )

    def _slash_command_infos(self) -> list[dict[str, Any]]:
        return [
            {
                "name": info.name,
                "description": info.description,
                "usage": info.usage,
                "aliases": list(info.aliases),
            }
            for info in self._slash_router.command_infos()
        ]

    async def _resume_preview(self) -> str:
        get_messages = getattr(self._session, "get_messages_slice", None)
        if not callable(get_messages):
            return ""
        messages = await get_messages()
        return render_resume_preview(messages, session_id=getattr(self._session, "session_id", None))

    async def _run_turn(self, request: dict[str, Any]) -> None:
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        query = str(params.get("input") or params.get("query") or "").strip()
        if not query:
            await self._respond_error(request, "turn.start requires input.", "InvalidRequest")
            return
        transient_system_messages = params.get("transient_system_messages")
        if not isinstance(transient_system_messages, list):
            transient_system_messages = None

        cancel_source = CancellationTokenSource()
        self._current_cancel = cancel_source
        try:
            async for event in self._runtime.run_turn(
                query=query,
                cancellation_token=cancel_source.token,
                transient_system_messages=transient_system_messages,
            ):
                await self._send_event(event.to_dict())
            await self._respond(request, {"ok": True})
        finally:
            self._current_cancel = None
            cancel_source.dispose()

    async def _compact(self, request: dict[str, Any]) -> None:
        record = await self._runtime.compact_context(reason="manual")
        await self._respond(request, record)

    async def _set_model(self, request: dict[str, Any]) -> None:
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        model = str(params.get("model") or "").strip()
        if not model:
            await self._respond_error(request, "model.set requires model.", "InvalidRequest")
            return
        Config.set_model(model)
        result = await self._runtime.set_model(model)
        await self._respond(request, result)

    async def _execute_slash(self, request: dict[str, Any]) -> None:
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        raw_input = str(params.get("input") or "")
        cancel_source = CancellationTokenSource()
        try:
            result = await self._slash_router.execute(
                raw_input,
                SlashCommandContext(
                    runtime=self._runtime,
                    session=self._session,
                    debug=self._debug,
                    cancellation_token=cancel_source.token,
                ),
            )
            await self._respond(
                request,
                {
                    "text": result.text,
                    "should_exit": result.should_exit,
                    "clear_screen": result.clear_screen,
                    "input_prefill": result.input_prefill,
                    "run_turn_input": result.run_turn_input,
                    "transient_system_messages": result.transient_system_messages,
                },
            )
        finally:
            cancel_source.dispose()

    async def _read_stdin(self) -> None:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":
                await self._requests.put(None)
                return
            message = self._parse_line(line)
            if message is None:
                continue
            if await self._handle_control_message(message):
                continue
            await self._requests.put(message)

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    async def _handle_control_message(self, message: dict[str, Any]) -> bool:
        method = str(message.get("method") or "")
        if method == "turn.interrupt":
            self._interrupt_current()
            await self._respond(message, {"ok": True})
            return True
        if method == "user_question.respond":
            await self._receive_user_answer(message)
            return True
        return False

    def _interrupt_current(self) -> None:
        if self._current_cancel and not self._current_cancel.token.is_cancelled:
            self._current_cancel.cancel("User interrupted")
        for future in self._pending_answers.values():
            if not future.done():
                future.set_result("")
        self._pending_answers.clear()

    async def _receive_user_answer(self, message: dict[str, Any]) -> None:
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        tool_call_id = str(params.get("tool_call_id") or "")
        answer = str(params.get("answer") or "").strip()
        future = self._pending_answers.pop(tool_call_id, None)
        if future is None:
            await self._respond_error(message, "No pending user question.", "QuestionNotFound")
            return
        if not future.done():
            future.set_result(answer)
        await self._respond(message, {"ok": True})

    async def _answer_user_question(self, event: UserQuestionRequestedEvent) -> str:
        future = asyncio.get_running_loop().create_future()
        self._pending_answers[event.tool_call_id] = future
        try:
            return await future
        finally:
            self._pending_answers.pop(event.tool_call_id, None)

    async def _respond(self, request: dict[str, Any], result: Any) -> None:
        await self._writer.send({"kind": "response", "id": request.get("id"), "result": result})

    async def _respond_error(self, request: dict[str, Any], message: str, error_type: str) -> None:
        await self._writer.send(
            {
                "kind": "response",
                "id": request.get("id"),
                "error": {"type": error_type, "message": message},
            }
        )

    async def _send_event(self, event: dict[str, Any]) -> None:
        await self._writer.send({"kind": "event", "event": event})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChainPeer headless runtime server")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--allow-unsafe-bash", action="store_true")
    parser.add_argument("--session", type=str, default=None)
    parser.add_argument("-c", "--resume-latest", action="store_true")
    parser.add_argument("--session-dir", type=str, default=None)
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.allow_unsafe_bash:
        os.environ["AGENT_ALLOW_UNSAFE_BASH"] = "1"
    if args.session is not None:
        try:
            args.session = validate_session_id(args.session)
        except ValueError as exc:
            print(f"Session error: {exc}", file=sys.stderr)
            return 1

    try:
        Config.ensure_user_settings_template()
        Config.reload()
        Config.validate()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    dependencies = build_basic_agent_dependencies(
        debug=args.debug,
        session_dir=args.session_dir,
        session_id=args.session,
        resume_latest=args.resume_latest,
    )
    server = StdioRuntimeServer(dependencies["runtime"], dependencies["session"], debug=args.debug)
    return await server.run()


def main(argv: list[str] | None = None) -> int:
    configure_stdio_server_signals()
    configure_utf8_stdio()
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
