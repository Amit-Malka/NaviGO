import pytest
import aiosqlite
from langchain_core.messages import HumanMessage
from app.db import DB_PATH, init_db
from app.agent.graph import init_checkpointer, close_checkpointer, get_graph_with_memory

@pytest.mark.asyncio
async def test_memory_persistence():
    session_id = "test_persistence_session"
    
    # Explicit initialization instead of fixture for simpler guarantee of order
    await init_db()
    await init_checkpointer()
    
    try:
        graph = get_graph_with_memory()
        
        # Verify checkpointer
        assert graph.checkpointer is not None
        
        # Verify tables created
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] async for row in cursor]
            assert "user_preferences" in tables
            assert "chat_threads" in tables
            
    finally:
        await close_checkpointer()
