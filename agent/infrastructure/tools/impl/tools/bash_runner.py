"""Executes bash commands asynchronously and handles streams."""

from __future__ import annotations

import asyncio
import codecs
import os
import uuid
from collections import deque
from dataclasses import dataclass, field

from agent.domain.jobs import ToolExecutionResult
from agent.domain import tool_ok
from agent.application.runtime.cancellation import CancellationToken
from .bash_session_pool import ShellState


@dataclass
class _BgProc:
    """In-flight state for a background process."""
    bg_id: str
    session_id: str
    process: asyncio.subprocess.Process
    stdout_head: list[str] = field(default_factory=list)
    stdout_tail: deque = field(default_factory=lambda: deque(maxlen=10000))
    stdout_len: list[int] = field(default_factory=lambda: [0])
    stderr_head: list[str] = field(default_factory=list)
    stderr_tail: deque = field(default_factory=lambda: deque(maxlen=10000))
    stderr_len: list[int] = field(default_factory=lambda: [0])
    exit_code: int | None = None
    _tasks: list[asyncio.Task] = field(default_factory=list)


class BashRunner:
    """Executes bash commands and captures their streams."""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self.HEAD_LIMIT = 10000
        self.TAIL_LIMIT = 10000
        self._bg: dict[str, _BgProc] = {}

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _handle_cd(self, command: str, state: ShellState) -> ToolExecutionResult | None:
        if command.strip().startswith("cd "):
            target_dir = command.strip()[3:].strip()
            if target_dir.startswith("~"):
                target_dir = os.path.expanduser(target_dir)
            new_path = os.path.abspath(os.path.join(state.cwd, target_dir))
            if os.path.exists(new_path) and os.path.isdir(new_path):
                state.cwd = new_path
                return ToolExecutionResult(
                    status="ok",
                    result_str=tool_ok("bash", {"stdout": f"Changed directory to: {state.cwd}", "stderr": "", "exit_code": 0, "cwd": state.cwd})
                )
            else:
                return ToolExecutionResult(
                    status="ok",
                    result_str=tool_ok("bash", {"stdout": "", "stderr": f"cd: no such file or directory: {target_dir}", "exit_code": 1, "cwd": state.cwd})
                )
        return None

    def _build_shell_cmd(self, command: str, state: ShellState) -> list[str]:
        shell_cmd = [state.shell_executable]
        if "bash" in state.shell_executable.lower():
            shell_cmd.extend(["-c", command])
        elif "powershell" in state.shell_executable.lower():
            shell_cmd.extend(["-Command", command])
        else:
            shell_cmd.extend(["/c", command])
        return shell_cmd

    def _build_output(self, head: list[str], tail: deque, total_len: int) -> str:
        if total_len <= self.HEAD_LIMIT:
            return "".join(head)
        if total_len <= self.HEAD_LIMIT + self.TAIL_LIMIT:
            return "".join(head) + "".join(tail)
        return "".join(head) + "\n\n...[OUTPUT TRUNCATED]...\n\n" + "".join(tail)

    def _append_chunk(self, chunk: str, head: list[str], tail: deque, length: list[int]) -> None:
        clen = len(chunk)
        cur = length[0]
        length[0] += clen
        space = self.HEAD_LIMIT - cur
        if space > 0:
            if clen <= space:
                head.append(chunk)
            else:
                head.append(chunk[:space])
                tail.extend(chunk[space:])
        else:
            tail.extend(chunk)

    async def _read_stream(self, stream: asyncio.StreamReader, head: list[str], tail: deque, length: list[int]) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            raw = await stream.read(4096)
            if not raw:
                flushed = decoder.decode(b"", True)
                if flushed:
                    self._append_chunk(flushed, head, tail, length)
                break
            self._append_chunk(decoder.decode(raw, False), head, tail, length)

    # ------------------------------------------------------------------
    # Foreground execution (existing behaviour)
    # ------------------------------------------------------------------

    async def run(
        self,
        command: str,
        state: ShellState,
        cancellation_token: CancellationToken | None = None,
    ) -> ToolExecutionResult:
        """Run a command and block until it exits or times out."""
        cd_result = self._handle_cd(command, state)
        if cd_result:
            return cd_result

        shell_cmd = self._build_shell_cmd(command, state)

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=state.cwd,
                env=state.env,
            )

            stdout_head: list[str] = []
            stdout_tail: deque = deque(maxlen=self.TAIL_LIMIT)
            stdout_len: list[int] = [0]
            stderr_head: list[str] = []
            stderr_tail: deque = deque(maxlen=self.TAIL_LIMIT)
            stderr_len: list[int] = [0]

            t_out = asyncio.create_task(self._read_stream(process.stdout, stdout_head, stdout_tail, stdout_len))
            t_err = asyncio.create_task(self._read_stream(process.stderr, stderr_head, stderr_tail, stderr_len))

            timeout_msg = ""
            wait_task = asyncio.create_task(process.wait())
            tasks_to_wait = [wait_task, t_out, t_err]

            cancel_task = None
            if cancellation_token:
                cancel_task = asyncio.create_task(cancellation_token.wait())
                tasks_to_wait.append(cancel_task)

            done, pending = await asyncio.wait(
                tasks_to_wait,
                timeout=self.timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                for p in pending:
                    p.cancel()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                timeout_msg = f"\n\n[PROCESS TERMINATED: Command timed out after {self.timeout} seconds.]"
                await process.wait()
            elif cancel_task and cancel_task in done:
                for p in pending:
                    p.cancel()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                timeout_msg = f"\n\n[PROCESS TERMINATED: Command cancelled: {cancellation_token.reason}]"
                await process.wait()
            else:
                if cancel_task:
                    cancel_task.cancel()
                await wait_task
                await asyncio.gather(t_out, t_err)

            stdout_final = self._build_output(stdout_head, stdout_tail, stdout_len[0])
            stderr_final = self._build_output(stderr_head, stderr_tail, stderr_len[0])

            if timeout_msg:
                stderr_final += timeout_msg

            return ToolExecutionResult(
                status="ok",
                result_str=tool_ok("bash", {
                    "stdout": stdout_final.strip(),
                    "stderr": stderr_final.strip(),
                    "exit_code": process.returncode if process.returncode is not None else -1,
                    "cwd": state.cwd,
                }),
                exit_code=process.returncode if process.returncode is not None else -1,
            )

        except Exception as e:
            return ToolExecutionResult(
                status="error",
                error_msg=str(e),
                error_type=type(e).__name__,
            )

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------

    async def run_background(self, command: str, state: ShellState, session_id: str = "default") -> ToolExecutionResult:
        """Spawn a process and return immediately with a bg_id."""
        shell_cmd = self._build_shell_cmd(command, state)

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=state.cwd,
                env=state.env,
            )

            bg_id = f"bg_{uuid.uuid4().hex[:8]}"
            bg = _BgProc(bg_id=bg_id, session_id=session_id, process=process)

            async def _drain():
                t_out = asyncio.create_task(self._read_stream(process.stdout, bg.stdout_head, bg.stdout_tail, bg.stdout_len))
                t_err = asyncio.create_task(self._read_stream(process.stderr, bg.stderr_head, bg.stderr_tail, bg.stderr_len))
                await process.wait()
                await asyncio.gather(t_out, t_err)
                bg.exit_code = process.returncode

            bg._tasks.append(asyncio.create_task(_drain()))
            self._bg[bg_id] = bg

            return ToolExecutionResult(
                status="ok",
                result_str=tool_ok("bash", {
                    "bg_id": bg_id,
                    "status": "running",
                    "message": f"Background process started: {command[:200]}",
                    "cwd": state.cwd,
                }),
            )
        except Exception as e:
            return ToolExecutionResult(
                status="error",
                error_msg=str(e),
                error_type=type(e).__name__,
            )

    def read_background(self, bg_id: str) -> ToolExecutionResult:
        """Read current accumulated output from a background process."""
        bg = self._bg.get(bg_id)
        if not bg:
            return ToolExecutionResult(status="error", error_msg=f"No background process: {bg_id}", error_type="NotFound")

        stdout = self._build_output(bg.stdout_head, bg.stdout_tail, bg.stdout_len[0])
        stderr = self._build_output(bg.stderr_head, bg.stderr_tail, bg.stderr_len[0])
        running = bg.exit_code is None

        return ToolExecutionResult(
            status="ok",
            result_str=tool_ok("bash_output", {
                "bg_id": bg_id,
                "status": "running" if running else "done",
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "exit_code": bg.exit_code if bg.exit_code is not None else -1,
            }),
        )

    def kill_background(self, bg_id: str) -> ToolExecutionResult:
        """Kill a background process and remove it from the registry."""
        bg = self._bg.pop(bg_id, None)
        if not bg:
            return ToolExecutionResult(status="error", error_msg=f"No background process: {bg_id}", error_type="NotFound")

        for t in bg._tasks:
            t.cancel()
        try:
            bg.process.kill()
        except ProcessLookupError:
            pass

        return ToolExecutionResult(
            status="ok",
            result_str=tool_ok("bash_output", {"bg_id": bg_id, "status": "killed"}),
        )

    def kill_session_backgrounds(self, session_id: str) -> None:
        """Kill all background processes belonging to a session."""
        to_kill = [bid for bid, bg in self._bg.items() if bg.session_id == session_id]
        for bid in to_kill:
            self.kill_background(bid)
