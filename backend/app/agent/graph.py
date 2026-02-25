"""LangGraph StateGraph — the full ReAct agent wiring."""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from app.agent.state import AgentState
from app.agent.nodes import (
    agent_node,
    tool_node,
    self_correction_node,
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

    # Entry point
    builder.set_entry_point("agent")

    # agent → tools or END
    builder.add_conditional_edges(
        "agent",
        should_use_tools,
        {"tools": "tools", "end": END},
    )

    # tools → self_correction or back to agent
    builder.add_conditional_edges(
        "tools",
        should_correct,
        {"self_correction": "self_correction", "agent": "agent"},
    )

    # self_correction always goes back to tools (to retry)
    builder.add_edge("self_correction", "tools")

    return builder.compile(checkpointer=checkpointer)


def get_graph_with_memory():
    """Return a graph compiled with in-memory checkpointer (session-scoped).

    We use MemorySaver for simplicity and reliability across langgraph versions.
    For production persistence, swap to AsyncSqliteSaver with proper lifecycle management.
    """
    saver = MemorySaver()
    return build_graph(checkpointer=saver)
