import os
from typing import Any

from agent.domain import tool_error, tool_ok
from .bash_session_pool import BashSessionPool
from .bash_policy import BashPolicy
from .bash_runner import BashRunner

# Global pool for compatibility with synchronous interface.
# In Phase 2, we use a single pool instead of a single shell session,
# allowing isolation per session_id (defaulting to "default" for CLI).
_POOL = BashSessionPool()
_RUNNER = BashRunner(timeout=120)


def bash(command: str, session_id: str = "default", _output_callback=None) -> str:
    """
    Execute a bash command in a session-scoped isolated shell.
    """
    status, reason = BashPolicy.classify(command)
    
    if status == "deny":
        return tool_error(
            "bash",
            f"Blocked forbidden command. {reason}",
            "DangerousCommandBlocked",
            meta={"command": command[:500]},
        )
        
    if status == "needs_approval":
        # In Phase 2, we do NOT block with input() here.
        # If the command needs approval, we return an error or a specific status 
        # requiring the upper layer to re-issue with an approval flag.
        # Since we haven't built the full CLI approval flow yet, we'll fail safe.
        return tool_error(
            "bash",
            f"Potentially dangerous command requires user approval: {reason}",
            "CommandRequiresApproval",
            meta={"command": command[:500]},
        )
        
    state = _POOL.get_state(session_id)
    result = _RUNNER.run_sync(command, state, output_callback=_output_callback)
    
    if result.status == "ok":
        return result.result_str
    else:
        return tool_error("bash", result.error_msg, result.error_type)


def kill_shell(session_id: str = "default") -> str:
    """
    Reset the Shell session for the given session_id.
    """
    _POOL.reset_state(session_id)
    return tool_ok("kill_shell", "Shell session reset successfully.")
