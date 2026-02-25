"""LangGraph StateGraph — the full ReAct agent wiring."""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.db import DB_PATH
from app.agent.state import AgentState
from app.agent.nodes import (
    agent_node,
    tool_node,
    self_correction_node,
    extract_preferences_node,
    should_use_tools,
    should_correct,
)


def build_graph(checkpointer=None):
    """Build and compile the NaviGO ReAct agent graph.

    Graph flow:
        agent → (has tool calls?) → tools → (errors?) → self_correction → agent
                                                       → agent (no errors)
        agent → (no tool calls) → END
    """
    builder = StateGraph(AgentState)

    # Nodes
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)
    builder.add_node("self_correction", self_correction_node)
    builder.add_node("extract_preferences", extract_preferences_node)

    # Entry point
    builder.set_entry_point("agent")

    # agent → tools or extract_preferences
    builder.add_conditional_edges(
        "agent",
        should_use_tools,
        {"tools": "tools", "end": "extract_preferences"},
    )

    # tools → self_correction or back to agent
    builder.add_conditional_edges(
        "tools",
        should_correct,
        {"self_correction": "self_correction", "agent": "agent"},
    )

    # self_correction always goes back to tools (to retry)
    builder.add_edge("self_correction", "tools")
    
    # After extract_preferences, we end the turn
    builder.add_edge("extract_preferences", END)

    return builder.compile(checkpointer=checkpointer)


# Global checkpointer instance
_db_conn = None
_saver = None

async def init_checkpointer():
    global _db_conn, _saver
    import aiosqlite
    _db_conn = await aiosqlite.connect(DB_PATH)
    _saver = AsyncSqliteSaver(_db_conn)
    await _saver.setup()

async def close_checkpointer():
    global _db_conn
    if _db_conn:
        await _db_conn.close()

def get_graph_with_memory():
    """Return a graph compiled with the database-backed sqlite checkpointer.

    We use AsyncSqliteSaver for persistent memory across sessions.
    """
    if _saver is None:
        raise RuntimeError("Checkpointer not initialized. Ensure init_checkpointer() was called.")
    return build_graph(checkpointer=_saver)
