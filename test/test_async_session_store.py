import pytest
import os
import shutil
import tempfile
import asyncio

from agent.infrastructure.persistence.jsonl_session_store import JsonlSessionStore
from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStoreFacade

@pytest.fixture
def temp_session_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

@pytest.mark.asyncio
async def test_async_session_store_facade(temp_session_dir):
    sync_store = JsonlSessionStore(session_dir=temp_session_dir, session_id="test_async_id")
    # For testing, ensure _session_root is set
    sync_store._session_root = temp_session_dir
    async_store = AsyncJsonlSessionStoreFacade(sync_store)
    
    await async_store.initialize()
    
    assert async_store.session_id == "test_async_id"
    
    # Test persistence
    await async_store.persist_message("user", "Hello World")
    
    # Load and verify
    messages = await async_store.load_messages()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello World"
    
    # Test concurrency isolation informally
    async def write_msgs(role, n):
        for i in range(n):
            await async_store.persist_message(role, f"msg_{i}")
            
    await asyncio.gather(
        write_msgs("assistant", 5),
        write_msgs("system", 5)
    )
    
    messages = await async_store.load_messages()
    assert len(messages) == 11 # 1 user + 5 assistant + 5 system
