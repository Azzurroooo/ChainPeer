"""Executes bash commands asynchronously and handles streams."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from collections import deque
from typing import AsyncIterator

from agent.domain.events import RuntimeEvent, ToolProgressEvent, ToolResultEvent
from agent.domain.jobs import ToolExecutionResult
from agent.domain import tool_error, tool_ok
from agent.application.runtime.cancellation import CancellationToken
from .bash_session_pool import ShellState


class BashRunner:
    """Executes bash commands and captures their streams."""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self.HEAD_LIMIT = 10000
        self.TAIL_LIMIT = 10000

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

    async def run_async(
        self, 
        command: str, 
        state: ShellState, 
        output_callback=None,
        cancellation_token: CancellationToken | None = None
    ) -> ToolExecutionResult:
        """Run a command asynchronously using asyncio.create_subprocess_exec."""
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
                env=state.env
            )
            
            stdout_head = []
            stdout_tail = deque(maxlen=self.TAIL_LIMIT)
            stdout_len = [0]
            
            stderr_head = []
            stderr_tail = deque(maxlen=self.TAIL_LIMIT)
            stderr_len = [0]
            
            async def read_stream(stream, head_list, tail_deque, length_counter, is_stdout=True):
                while True:
                    # Read bytes and decode
                    chunk_bytes = await stream.read(4096)
                    if not chunk_bytes:
                        break
                        
                    chunk = chunk_bytes.decode('utf-8', errors='replace')
                        
                    if output_callback:
                        if asyncio.iscoroutinefunction(output_callback):
                            await output_callback(chunk, "stdout" if is_stdout else "stderr")
                        else:
                            output_callback(chunk, "stdout" if is_stdout else "stderr")
                    
                    chunk_len = len(chunk)
                    current_len = length_counter[0]
                    length_counter[0] += chunk_len
                    
                    head_space = self.HEAD_LIMIT - current_len
                    if head_space > 0:
                        if chunk_len <= head_space:
                            head_list.append(chunk)
                        else:
                            head_list.append(chunk[:head_space])
                            tail_deque.extend(chunk[head_space:])
                    else:
                        tail_deque.extend(chunk)

            t_out = asyncio.create_task(read_stream(process.stdout, stdout_head, stdout_tail, stdout_len, True))
            t_err = asyncio.create_task(read_stream(process.stderr, stderr_head, stderr_tail, stderr_len, False))
            
            timeout_msg = ""
            
            wait_task = asyncio.create_task(process.wait())
            tasks_to_wait = [wait_task, t_out, t_err]
            
            if cancellation_token:
                cancel_task = asyncio.create_task(cancellation_token.wait())
                tasks_to_wait.append(cancel_task)
                
            done, pending = await asyncio.wait(
                tasks_to_wait,
                timeout=self.timeout,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if not done:
                # Timeout occurred
                for p in pending:
                    p.cancel()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                timeout_msg = f"\n\n[PROCESS TERMINATED: Command timed out after {self.timeout} seconds.]"
                await process.wait()
            else:
                if cancellation_token and cancel_task in done:
                    # Cancelled
                    for p in pending:
                        p.cancel()
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    timeout_msg = f"\n\n[PROCESS TERMINATED: Command cancelled: {cancellation_token.reason}]"
                    await process.wait()
                else:
                    # Finished normally
                    if cancellation_token:
                        cancel_task.cancel()
                    await asyncio.gather(t_out, t_err)

            stdout_final = self._build_output(stdout_head, stdout_tail, stdout_len[0])
            stderr_final = self._build_output(stderr_head, stderr_tail, stderr_len[0])
            
            if timeout_msg:
                stderr_final += timeout_msg
                
            # If we cancelled, we might want to return an error status or ok with stderr info
            # For bash, we can return ok with the stderr containing the termination message
            return ToolExecutionResult(
                status="ok",
                result_str=tool_ok("bash", {
                    "stdout": stdout_final.strip(), 
                    "stderr": stderr_final.strip(), 
                    "exit_code": process.returncode if process.returncode is not None else -1, 
                    "cwd": state.cwd
                }),
                exit_code=process.returncode if process.returncode is not None else -1
            )

        except Exception as e:
            return ToolExecutionResult(
                status="error",
                error_msg=str(e),
                error_type=type(e).__name__
            )

    def run_sync(self, command: str, state: ShellState, output_callback=None) -> ToolExecutionResult:
        """Run a command synchronously, mostly for compatibility.
        If output_callback is provided, it will be called with incremental chunks.
        """
        # This is a candidate for dead code removal, but kept for compatibility during transition
        return asyncio.run(self.run_async(command, state, output_callback))
