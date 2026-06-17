import asyncio
import json
import os
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.interfaces.runtime_server.stdio import (
    JsonlWriter,
    StdioRuntimeServer,
    configure_stdio_server_signals,
    configure_utf8_stdio,
)


class _Runtime:
    def set_user_question_responder(self, responder):
        self.responder = responder

    async def initialize(self):
        return None

    async def compact_context(self, reason="manual", cancellation_token=None):
        return {
            "id": "compact-1",
            "source": {
                "message_start_index": 1,
                "message_end_index_exclusive": 3,
                "tool_call_ids": ["tool-1"],
            },
        }


class _Session:
    session_id = "s1"
    model = "m1"


def test_question_response_completes_pending_future():
    async def run():
        server = StdioRuntimeServer(_Runtime(), _Session())
        event = type("Event", (), {"tool_call_id": "call-1"})()
        task = asyncio.create_task(server._answer_user_question(event))
        await asyncio.sleep(0)
        await server._receive_user_answer(
            {"id": 1, "method": "user_question.respond", "params": {"tool_call_id": "call-1", "answer": "yes"}}
        )
        return await task

    assert asyncio.run(run()) == "yes"


def test_jsonl_writer_uses_compact_json(capsys):
    async def run():
        await JsonlWriter().send({"kind": "event", "event": {"type": "turn_completed"}})

    asyncio.run(run())
    assert capsys.readouterr().out == '{"kind":"event","event":{"type":"turn_completed"}}\n'


def test_initialize_response_includes_resume_preview_when_history_exists(capsys):
    class Session:
        session_id = "s1"
        model = "m1"

        async def get_messages_slice(self):
            return [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]

    async def run():
        server = StdioRuntimeServer(_Runtime(), Session())
        await server._initialize({"id": 7, "method": "initialize", "params": {}})

    asyncio.run(run())

    message = json.loads(capsys.readouterr().out)
    result = message["result"]
    assert result["session_id"] == "s1"
    assert result["model"] == "m1"
    assert "Resumed session s1" in result["resume_preview"]
    assert "- user: hello" in result["resume_preview"]
    assert any(command["name"] == "status" for command in result["slash_commands"])


def test_slash_execute_reuses_cli_router(capsys):
    async def run():
        server = StdioRuntimeServer(_Runtime(), _Session())
        await server._execute_slash({"id": 8, "method": "slash.execute", "params": {"input": "/compact"}})

    asyncio.run(run())

    message = json.loads(capsys.readouterr().out)
    result = message["result"]
    assert result["should_exit"] is False
    assert result["clear_screen"] is False
    assert result["text"].startswith("Compact complete.")


class _TextStream:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_configure_utf8_stdio_pins_protocol_stream_encoding(monkeypatch):
    streams = [_TextStream(), _TextStream(), _TextStream()]
    monkeypatch.setattr(sys, "stdin", streams[0])
    monkeypatch.setattr(sys, "stdout", streams[1])
    monkeypatch.setattr(sys, "stderr", streams[2])

    configure_utf8_stdio()

    assert [stream.calls for stream in streams] == [
        [{"encoding": "utf-8", "errors": "replace"}],
        [{"encoding": "utf-8", "errors": "replace"}],
        [{"encoding": "utf-8", "errors": "replace"}],
    ]


def test_configure_stdio_server_signals_ignores_console_sigint(monkeypatch):
    calls = []

    def fake_signal(signum, handler):
        calls.append((signum, handler))

    monkeypatch.setattr(signal, "signal", fake_signal)

    configure_stdio_server_signals()

    assert calls == [(signal.SIGINT, signal.SIG_IGN)]
