import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent.infrastructure.llm.openai_async_chat_client import AsyncOpenAIChatClient
from agent.application.runtime.cancellation import CancellationTokenSource

@pytest.mark.asyncio
async def test_openai_async_client_cancellation():
    mock_openai = MagicMock()
    mock_create = AsyncMock()
    
    # Simulate a slow API call
    async def slow_create(*args, **kwargs):
        await asyncio.sleep(0.5)
        return "Done"
        
    mock_create.side_effect = slow_create
    mock_openai.chat.completions.create = mock_create
    
    client = AsyncOpenAIChatClient(mock_openai, "test-model")
    source = CancellationTokenSource()
    
    # Schedule cancellation
    async def cancel_later():
        await asyncio.sleep(0.1)
        source.cancel("Timeout")
        
    asyncio.create_task(cancel_later())
    
    with pytest.raises(asyncio.CancelledError) as exc:
        await client.create([{"role": "user", "content": "hi"}], cancellation_token=source.token)
        
    assert "Timeout" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_async_client_close_stream_prefers_aclose():
    class FakeStream:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    stream = FakeStream()
    client = AsyncOpenAIChatClient(MagicMock(), "test-model")

    await client._close_stream(stream)

    assert stream.closed is True


@pytest.mark.asyncio
async def test_openai_async_client_close_stream_accepts_sync_close():
    class FakeStream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    stream = FakeStream()
    client = AsyncOpenAIChatClient(MagicMock(), "test-model")

    await client._close_stream(stream)

    assert stream.closed is True
