import pytest
import openai
from tenacity import RetryError
from agent.application.runtime import AgentRuntime
from agent.application.ports import SessionStore
from agent.application.services import ContextManager, ContextBudget, ContextEstimator
from agent.domain import ParsedToolCall

class DummyChatClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        
    def create(self, **kwargs):
        resp = self.responses[self.calls]
        self.calls += 1
        if isinstance(resp, Exception):
            raise resp
        return resp

class DummySession(SessionStore):
    def __init__(self):
        self.messages = []
        self.snapshots = []
        self.tool_calls = []
    
    def now_iso(self):
        return "2026-05-08T00:00:00Z"
        
    def get_messages_slice(self, **kwargs):
        return self.messages
        
    def persist_message(self, role, content, **kwargs):
        self.messages.append({"role": role, "content": content})
        
    def persist_context_snapshot(self, snapshot):
        self.snapshots.append(snapshot)
        
    def get_tool_records(self, **kwargs):
        return []
        
    def get_tool_summaries(self, **kwargs):
        return {}
        
    def persist_tool_call(self, call_id, name, args, raw_args, ts_start, ts_end, result):
        self.tool_calls.append({"id": call_id, "result": result})

def test_chaos_llm_malformed_json_tool_call():
    """
    Step 5.2: Chaos Engineering Test for Malformed Tool Call JSON
    Simulate an LLM returning a malformed JSON tool call and assert the system recovers gracefully.
    """
    class MalformedMessage:
        content = "I will use a tool"
        class ToolCall:
            id = "call_123"
            class Function:
                name = "some_tool"
                arguments = "{ this is completely broken json"
            function = Function()
        tool_calls = [ToolCall()]

    class GoodMessage:
        content = "Oh, I messed up"
        tool_calls = []

    class MockResponse:
        def __init__(self, msg):
            self.choices = [type('Choice', (), {'message': msg})()]

    # 第一轮返回一个损坏的 tool_calls json，第二轮恢复正常
    client = DummyChatClient([MockResponse(MalformedMessage()), MockResponse(GoodMessage())])
    
    class DummyToolExecutor:
        def execute(self, name, parsed_args, raw_args=""):
            return "Should not be called with parsed args"
            
    runtime = AgentRuntime(
        chat_client=client,
        tool_executor=DummyToolExecutor(),
        tool_schemas=[],
        debug=True
    )
    
    session = DummySession()
    
    # 这一步不应该崩溃
    runtime.process_user_turn(session, on_content=lambda x: None)
    
    # 验证第一轮产生的 ToolArgsJSONError 被作为 tool 结果持久化并回传
    tool_error_msg = [m for m in session.messages if m["role"] == "tool"]
    assert len(tool_error_msg) == 1
    
    assert len(session.tool_calls) == 1
    assert "Invalid tool arguments JSON" in session.tool_calls[0]["result"]
    assert "ToolArgsJSONError" in session.tool_calls[0]["result"]

def test_chaos_context_length_rescue():
    """
    Step 5.3: Chaos Engineering Test for ContextLengthExceeded Rescue
    Simulate ContextLengthExceeded error and ensure the runtime shrinks the hard limit and triggers Context Rescue.
    """
    class GoodMessage:
        content = "I survived the rescue!"
        tool_calls = []
        
    class MockResponse:
        def __init__(self, msg):
            self.choices = [type('Choice', (), {'message': msg})()]

    # 第一次调用抛出 400 ContextLengthExceeded，第二次返回成功
    import httpx
    mock_request = httpx.Request("POST", "http://dummy")
    mock_response = httpx.Response(400, request=mock_request)
    err = openai.BadRequestError("maximum context length exceeded", response=mock_response, body=None)
    client = DummyChatClient([err, MockResponse(GoodMessage())])
    
    manager = ContextManager(estimator=ContextEstimator(ContextBudget(hard_limit_tokens=1000)))
    runtime = AgentRuntime(
        chat_client=client,
        tool_executor=None,
        tool_schemas=[],
        context_manager=manager,
        debug=True
    )
    
    session = DummySession()
    # 伪造很多冷消息
    for i in range(20):
        session.messages.append({"role": "user", "content": f"Cold user {i}"})
        session.messages.append({"role": "assistant", "content": f"Cold assistant {i}"})
        
    # 添加一个最新的 hot message
    session.messages.append({"role": "user", "content": "Hot user"})
    
    # 应该被捕获并急救，不会崩溃抛出
    runtime.process_user_turn(session, on_content=lambda x: None)
    
    # 验证 hard limit 被成功缩小了 20%
    assert manager._estimator.budget.hard_limit_tokens == 800
    
    # 验证大模型成功回复了
    assert session.messages[-1]["content"] == "I survived the rescue!"
