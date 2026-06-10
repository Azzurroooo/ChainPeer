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


def test_system_prompt_contains_chainpeer_doc_rules():
    text = prompts.SYSTEM_PROMPT

    assert "CHAINPEER.md Context Docs" in text
    assert "32 KiB byte budget" in text
    assert "Never create, update, delete, or rename any `CHAINPEER.md`" in text
    assert "not automatically updated memory" in text


def test_system_prompt_describes_path_roots():
    text = prompts.SYSTEM_PROMPT

    assert "cd` commands affect subsequent `bash` calls only" in text
    assert "file tools still resolve relative paths from the Current Working Directory" in text
    assert "Project-level `CHAINPEER.md` and project skills are rooted at the Current Working Directory" in text


def test_chainpeer_init_prompt_scopes_project_file():
    prompt = prompts.build_chainpeer_init_prompt("project", r"C:\repo\CHAINPEER.md")

    assert "project-level ChainPeer context document" in prompt
    assert r"C:\repo\CHAINPEER.md" in prompt
    assert "Explore the project lightly before writing" in prompt
    assert "Do not modify the other CHAINPEER.md level." in prompt
    assert "32 KiB byte budget" in prompt


def test_chainpeer_init_prompt_scopes_user_file():
    prompt = prompts.build_chainpeer_init_prompt("user", r"C:\Users\me\.chainpeer\CHAINPEER.md")

    assert "user-level ChainPeer context document" in prompt
    assert "Do not copy project facts into the user-level file." in prompt
    assert "Do not invent preferences." in prompt
    assert r"C:\Users\me\.chainpeer\CHAINPEER.md" in prompt
