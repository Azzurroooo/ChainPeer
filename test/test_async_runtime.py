import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.domain.events import (
    AssistantDeltaEvent, 
    AssistantMessageCompletedEvent, 
    TurnCompletedEvent,
    TurnCancelledEvent,
    TurnFailedEvent
)
from agent.application.runtime.cancellation import CancellationTokenSource

@pytest.mark.asyncio
async def test_async_turn_runner_stream():
    mock_client = AsyncMock()
    
    # Mock stream response
    async def mock_stream(*args, **kwargs):
        class MockDelta:
            def __init__(self, content):
                self.content = content
                self.tool_calls = None
        class MockChoice:
            def __init__(self, content):
                self.delta = MockDelta(content)
        class MockChunk:
            def __init__(self, content):
                self.choices = [MockChoice(content)]
                
        yield MockChunk("Hello ")
        yield MockChunk("World!")
        
    mock_client.stream = mock_stream
    
    mock_processor = MagicMock()
    mock_processor.execute_tool_calls = MagicMock()
    
    mock_parser = MagicMock()
    mock_parser.parse_tool_calls_from_message.return_value = []
    
    # We must mock consume_async_stream because AsyncTurnRunner uses it
    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        await on_content_async("Hello ")
        await on_content_async("World!")
        return "Hello World!", []
    mock_parser.consume_async_stream = mock_consume
    
    mock_context = MagicMock()
    mock_context_async_method = AsyncMock()
    mock_context_async_method.return_value = MagicMock(messages=[])
    mock_context.build_messages_async = mock_context_async_method
    
    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"
    mock_session.persist_message = AsyncMock()
    
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=mock_processor,
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context
    )
    
    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)
        
    assert len(events) == 4
    assert isinstance(events[0], AssistantDeltaEvent)
    assert events[0].text == "Hello "
    assert isinstance(events[1], AssistantDeltaEvent)
    assert events[1].text == "World!"
    assert isinstance(events[2], AssistantMessageCompletedEvent)
    assert isinstance(events[3], TurnCompletedEvent)

@pytest.mark.asyncio
async def test_async_turn_runner_cancellation():
    mock_client = AsyncMock()
    
    async def mock_stream(*args, **kwargs):
        yield MagicMock()
        await asyncio.sleep(0.1) # Simulate delay
        
    mock_client.stream = mock_stream
    
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=MagicMock(),
        tool_schemas=[],
        context_manager=MagicMock()
    )
    
    source = CancellationTokenSource()
    source.cancel("User cancelled")
    
    events = []
    async for event in runner.run_turn(MagicMock(), cancellation_token=source.token):
        events.append(event)
        
    assert len(events) == 1
    assert isinstance(events[0], TurnCancelledEvent)
    assert events[0].reason == "User cancelled"


@pytest.mark.asyncio
async def test_async_turn_runner_stream_cancelled_error_is_cancelled_event():
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    mock_parser = MagicMock()

    async def mock_consume(*args, **kwargs):
        raise asyncio.CancelledError("stream cancelled")

    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], decisions={}))

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context
    )

    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], TurnCancelledEvent)
    assert events[0].reason == "stream cancelled"
    assert not any(isinstance(event, TurnFailedEvent) for event in events)
