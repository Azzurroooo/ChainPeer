"""Manages isolated shell sessions."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field


@dataclass
class ShellState:
    """State for a single isolated shell session."""
    cwd: str
    env: dict[str, str]
    shell_executable: str


class BashSessionPool:
    """Manages isolated shell states per session."""

    def __init__(self):
        self._states: dict[str, ShellState] = {}
        self._default_executable = self._detect_shell()

    def _detect_shell(self) -> str:
        """Detect the available shell executable."""
        system = platform.system()
        if system == "Windows":
            bash_path = shutil.which("bash")
            if bash_path:
                return bash_path
            pwsh_path = shutil.which("powershell")
            if pwsh_path:
                return pwsh_path
            return "cmd.exe"
        else:
            return shutil.which("bash") or "bash"

    def get_state(self, session_id: str) -> ShellState:
        """Get or create the shell state for a session."""
        if session_id not in self._states:
            self._states[session_id] = ShellState(
                cwd=os.getcwd(),
                env=os.environ.copy(),
                shell_executable=self._default_executable
            )
        return self._states[session_id]

    def reset_state(self, session_id: str) -> None:
        """Reset the shell state for a session."""
        if session_id in self._states:
            del self._states[session_id]
