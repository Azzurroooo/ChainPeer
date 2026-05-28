import agent.prompts as prompts


class FakeShellPool:
    def __init__(self, backend: str, executable: str | None):
        self._default_backend = backend
        self._default_executable = executable


def test_system_info_omits_start_time(monkeypatch):
    monkeypatch.setattr(prompts, "BashSessionPool", lambda: FakeShellPool("bash", "/bin/bash"))

    info = prompts.get_system_info()

    assert "Start Time:" not in info
    assert "Start Time:" not in prompts.SYSTEM_PROMPT


def test_system_info_uses_detected_shell_backend(monkeypatch):
    shell_path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    monkeypatch.setattr(prompts, "BashSessionPool", lambda: FakeShellPool("powershell", shell_path))

    info = prompts.get_system_info()

    assert "Shell Type: PowerShell" in info
    assert f"Shell Executable: {shell_path}" in info
