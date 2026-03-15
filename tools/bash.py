import subprocess
import os
import platform
import shutil
from typing import Optional, Tuple

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
                    return f"Changed directory to: {self.cwd}"
                else:
                    return f"cd: no such file or directory: {target_dir}"

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
            
            stdout = process.stdout.strip()
            stderr = process.stderr.strip()
            
            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if stderr:
                # 在 Bash 中 stderr 不一定是错误（比如 git 的进度条），但这里我们都收集
                output_parts.append(f"[Stderr]:\n{stderr}")
            
            result = "\n".join(output_parts)
            return result if result else "(Command executed with no output)"

        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {self.timeout} seconds."
        except Exception as e:
            return f"Error executing command: {str(e)}"

# 全局单例会话
_SESSION = ShellSession()

def bash(command: str) -> str:
    """
    执行 Shell 命令。
    """
    return _SESSION.run(command)

def kill_shell() -> str:
    """
    重置 Shell 会话 (清除环境变量和目录状态)。
    """
    global _SESSION
    _SESSION = ShellSession()
    return "Shell session reset successfully."
