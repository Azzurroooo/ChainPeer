import json
import pytest
import subprocess
from unittest.mock import MagicMock
from agent.infrastructure.tools.impl.tools.bash import bash, _SESSION

def test_bash_truncation_large_output(monkeypatch):
    """
    Step 5.1: Chaos Engineering Test for Bash Tool
    Simulate a bash command outputting 50,000 characters and assert it truncates correctly without OOM.
    """
    # 模拟一个疯狂输出日志的命令
    res = bash("python -c \"print('A' * 50000)\"")
    parsed = json.loads(res)
    
    assert parsed["ok"] is True
    assert parsed["tool"] == "bash"
    
    stdout = parsed["data"]["stdout"]
    
    # 我们不再直接检查 content 的截断标记，而是利用 _build_tool_content 的结果，
    # 或者直接检查被我们重写后的工具返回
    assert len(stdout) <= 25000
    assert "TRUNCATED" in stdout
    
    # 验证头尾数据被正确保留
    # Since python's print adds a newline, we should account for it.
    # The output from bash includes the stdout.
    assert stdout.startswith("A" * 100)
    assert stdout.strip().endswith("A" * 100)

def test_bash_timeout(monkeypatch):
    """Test that a stuck process is killed after timeout."""
    # Temporarily reduce timeout for the test
    original_timeout = _SESSION.timeout
    _SESSION.timeout = 1
    
    try:
        # Sleep for 3 seconds, which exceeds the 1 second timeout
        res = bash("python -c \"import time; time.sleep(3)\"")
        parsed = json.loads(res)
        
        assert parsed["ok"] is True
        assert "PROCESS TERMINATED: Command timed out" in parsed["data"]["stderr"]
    finally:
        _SESSION.timeout = original_timeout
