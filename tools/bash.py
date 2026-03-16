import subprocess
import os
import platform
import shutil
import re
from typing import Any

from tools.base import tool_ok, tool_error

class ShellSession:
    """
    一个持久化的 Shell 会话管理器。
    支持跨平台的命令执行，优先使用 Bash，并维护当前工作目录 (CWD)。
    """
    def __init__(self):
        self.cwd = os.getcwd()
        self.env = os.environ.copy()
        self.timeout = 120  # 命令执行超时时间 (秒)
        self.shell_executable = self._detect_shell()

    def _detect_shell(self) -> str:
        """
        检测可用的 Shell。
        Windows: 优先 Git Bash (bash.exe)，其次 PowerShell，最后 CMD。
        Unix: 默认使用 bash。
        """
        system = platform.system()
        if system == "Windows":
            # 1. 尝试寻找 Git Bash 或 WSL bash
            bash_path = shutil.which("bash")
            if bash_path:
                return bash_path
            
            # 2. 尝试 PowerShell
            pwsh_path = shutil.which("powershell")
            if pwsh_path:
                return pwsh_path
                
            # 3. 回退到 CMD
            return "cmd.exe"
        else:
            # Linux/MacOS
            return shutil.which("bash") or "bash"

    def run(self, command: str) -> str:
        """
        在当前会话中执行命令。
        """
        try:
            # 处理 cd 命令 (这是内置命令，不能直接传给 subprocess)
            if command.strip().startswith("cd "):
                target_dir = command.strip()[3:].strip()
                # 处理 ~
                if target_dir.startswith("~"):
                    target_dir = os.path.expanduser(target_dir)
                
                # 计算绝对路径
                new_path = os.path.abspath(os.path.join(self.cwd, target_dir))
                
                if os.path.exists(new_path) and os.path.isdir(new_path):
                    self.cwd = new_path
                    return tool_ok("bash", {"stdout": f"Changed directory to: {self.cwd}", "stderr": "", "exit_code": 0, "cwd": self.cwd})
                else:
                    return tool_ok("bash", {"stdout": "", "stderr": f"cd: no such file or directory: {target_dir}", "exit_code": 1, "cwd": self.cwd})

            # 构建实际执行的命令
            shell_cmd = [self.shell_executable]
            if "bash" in self.shell_executable.lower():
                shell_cmd.extend(["-c", command])
            elif "powershell" in self.shell_executable.lower():
                shell_cmd.extend(["-Command", command])
            else: # cmd
                shell_cmd.extend(["/c", command])

            process = subprocess.run(
                shell_cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                env=self.env,
                timeout=self.timeout
            )
            
            stdout = (process.stdout or "").strip()
            stderr = (process.stderr or "").strip()
            return tool_ok(
                "bash",
                {"stdout": stdout, "stderr": stderr, "exit_code": process.returncode, "cwd": self.cwd},
            )

        except subprocess.TimeoutExpired:
            return tool_error("bash", f"Command timed out after {self.timeout} seconds.", "Timeout")
        except Exception as e:
            return tool_error("bash", str(e), type(e).__name__)

# 全局单例会话
_SESSION = ShellSession()

def _match_patterns(command: str, patterns: list[tuple[str, str]]) -> str | None:
    s = command.strip()
    if not s:
        return None
    for pat, reason in patterns:
        if re.search(pat, s, flags=re.IGNORECASE):
            return reason
    return None

def _is_forbidden_command(command: str) -> str | None:
    patterns: list[tuple[str, str]] = [
        (r"\bformat\b", "Detected format command."),
        (r"\bmkfs\b", "Detected mkfs command."),
        (r"\bshutdown\b", "Detected shutdown command."),
        (r"\breboot\b", "Detected reboot command."),
        (r":\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "Detected fork bomb pattern."),
    ]
    return _match_patterns(command, patterns)

def _is_confirmable_command(command: str) -> str | None:
    patterns: list[tuple[str, str]] = [
        (r"\brm\b", "Detected rm command."),
        (r"\bdel\b.*\s/([qs]|s)\b", "Detected Windows del with recursive/silent flags."),
        (r"\brmdir\b.*\s/([qs]|s)\b", "Detected Windows rmdir with recursive/silent flags."),
        (r"\bRemove-Item\b.*-Recurse\b", "Detected PowerShell recursive removal."),
    ]
    return _match_patterns(command, patterns)

def _unsafe_mode_enabled() -> bool:
    value = os.getenv("AGENT_ALLOW_UNSAFE_BASH", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}

def bash(command: str) -> str:
    forbidden = _is_forbidden_command(command)
    if forbidden:
        return tool_error(
            "bash",
            f"Blocked forbidden command. {forbidden}",
            "DangerousCommandBlocked",
            meta={"command": command[:500]},
        )
    reason = _is_confirmable_command(command)
    if reason and not _unsafe_mode_enabled():
        answer = input(f"\nPotentially dangerous command detected.\nReason: {reason}\nCommand: {command}\nAllow? (y/N): ").strip().lower()
        if answer not in {"y", "yes"}:
            return tool_ok(
                "bash",
                {"stdout": "", "stderr": "User declined command execution.", "exit_code": 1, "cwd": _SESSION.cwd},
            )
    return _SESSION.run(command)

def kill_shell() -> str:
    """
    重置 Shell 会话 (清除环境变量和目录状态)。
    """
    global _SESSION
    _SESSION = ShellSession()
    return tool_ok("kill_shell", "Shell session reset successfully.")
