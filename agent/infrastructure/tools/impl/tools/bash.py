from __future__ import annotations

from agent.domain import tool_error, tool_ok
from agent.application.runtime.cancellation import CancellationToken
from .bash_session_pool import BashSessionPool
from .bash_policy import BashPolicy
from .bash_runner import BashRunner

_POOL = BashSessionPool()
_RUNNER = BashRunner(timeout=120)


async def bash(command: str, session_id: str = "default", run_in_background: bool = False, _cancellation_token: CancellationToken | None = None) -> str:
    """Execute a bash command. Use run_in_background=true for long-running commands like servers."""
    status, reason = BashPolicy.classify(command)

    if status == "deny":
        return tool_error(
            "bash",
            f"Blocked forbidden command. {reason}",
            "DangerousCommandBlocked",
            meta={"command": command[:500]},
        )

    if status == "needs_approval":
        return tool_error(
            "bash",
            f"Potentially dangerous command requires user approval: {reason}",
            "CommandRequiresApproval",
            meta={"command": command[:500]},
        )

    state = _POOL.get_state(session_id)

    if run_in_background:
        result = await _RUNNER.run_background(command, state, session_id=session_id)
    else:
        result = await _RUNNER.run(command, state, cancellation_token=_cancellation_token)

    if result.status == "ok":
        return result.result_str
    else:
        return tool_error("bash", result.error_msg, result.error_type)


def bash_output(bg_id: str, kill: bool = False) -> str:
    """
    Read output from a background process, or terminate it.
    :param bg_id: Background process ID returned by bash(run_in_background=true)
    :param kill: Set to true to terminate the process (default false = read only)
    """
    if kill:
        result = _RUNNER.kill_background(bg_id)
    else:
        result = _RUNNER.read_background(bg_id)

    if result.status == "ok":
        return result.result_str
    else:
        return tool_error("bash_output", result.error_msg, result.error_type)


def kill_shell(session_id: str = "default") -> str:
    """Reset the Shell session and kill all its background processes."""
    _RUNNER.kill_session_backgrounds(session_id)
    _POOL.reset_state(session_id)
    return tool_ok("kill_shell", "Shell session reset. All background processes killed.")
