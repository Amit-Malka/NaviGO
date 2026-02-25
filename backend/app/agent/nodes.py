"""LangGraph ReAct agent nodes."""
import json
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel
import aiosqlite
from app.config import settings
from app.db import DB_PATH
from app.agent.state import AgentState
from app.agent.prompts import REACT_SYSTEM_PROMPT
from app.tools.amadeus_flights import search_flights, search_airport_by_city
from app.tools.adsbdb import search_aircraft_by_callsign, search_aircraft_by_registration
from app.tools.google_docs import create_trip_document
from app.tools.google_calendar import create_calendar_event

# ── LLM Setup ────────────────────────────────────────────────────────────────

def get_llm():
    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0.3,  # lower for more deterministic planning
        streaming=True,
    )


ALL_TOOLS = [
    search_flights,
    search_airport_by_city,
    search_aircraft_by_callsign,
    search_aircraft_by_registration,
    create_trip_document,
    create_calendar_event,
]

MAX_RETRIES = 2

# ── Node: Agent (Reasoning + Planning) ───────────────────────────────────────

async def agent_node(state: AgentState) -> dict:
    """Main ReAct reasoning node. The LLM thinks, plans, and decides tool calls."""
    llm = get_llm()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    messages = [SystemMessage(content=REACT_SYSTEM_PROMPT)] + state["messages"]

    # Inject context
    preferences = []
    try:
        session_id = state.get("session_id", "default")
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT preferences_json FROM user_preferences WHERE user_id = ?", (session_id,))
            row = await cursor.fetchone()
            if row:
                preferences = json.loads(row[0])
    except Exception as e:
        print(f"Error fetching preferences: {e}")

    context = ""
    if state.get("trip_info"):
        context += f"\n\n[Current trip info extracted so far: {json.dumps(state['trip_info'])}]"
    if preferences:
        context += f"\n\n[User's Past Preferences: {json.dumps(preferences)}]"

    if context:
        messages[0] = SystemMessage(content=REACT_SYSTEM_PROMPT + context)

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


# ── Node: Tool Executor ───────────────────────────────────────────────────────

async def tool_node(state: AgentState) -> dict:
    """Execute all tool calls from the last AI message."""
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    tool_map = {t.name: t for t in ALL_TOOLS}
    results = []
    tool_messages = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        tool_fn = tool_map.get(tool_name)
        if not tool_fn:
            result = {"error": f"Unknown tool: {tool_name}"}
        else:
            try:
                # Inject google_token if needed and available
                if tool_name in ["create_trip_document", "create_calendar_event"]:
                    if state.get("google_token"):
                        tool_args["google_token_json"] = json.dumps(state["google_token"])
                    else:
                        result = {"error": "Google authentication required. Please grant permissions first."}
                        results.append({"tool": tool_name, **result})
                        tool_messages.append(ToolMessage(
                            content=json.dumps(result),
                            tool_call_id=tool_id,
                        ))
                        continue

                # Execute the tool
                if hasattr(tool_fn, "ainvoke"):
                    result = await tool_fn.ainvoke(tool_args)
                else:
                    result = tool_fn.invoke(tool_args)

            except Exception as e:
                import traceback
                traceback.print_exc()
                result = {"error": f"Tool execution failed: {str(e)}"}

        print(f"Tool {tool_name} returned: {result}")
        results.append({"tool": tool_name, **result})
        tool_messages.append(ToolMessage(
            content=json.dumps(result) if isinstance(result, dict) else str(result),
            tool_call_id=tool_id,
        ))

    return {
        "messages": tool_messages,
        "tool_results": results,
    }


# ── Node: Self-Correction ─────────────────────────────────────────────────────

async def self_correction_node(state: AgentState) -> dict:
    """Analyzes tool errors and generates a corrected approach."""
    llm = get_llm()
    retry_count = state.get("retry_count", 0)
    tool_results = state.get("tool_results", [])

    errors = [r for r in tool_results if "error" in r]
    if not errors:
        return {}

    error_summary = "\n".join([
        f"- Tool '{e['tool']}' failed: {e['error']}" for e in errors
    ])
    correction_hints = "\n".join([
        f"  Hint: {e['correction_hint']}" for e in errors if "correction_hint" in e
    ])

    correction_prompt = (
        f"The following tool calls failed:\n{error_summary}\n"
        f"{correction_hints}\n\n"
        f"This is retry attempt {retry_count + 1} of {MAX_RETRIES}.\n"
        f"Please analyze what went wrong, correct your approach, and try again. "
        f"State your correction reasoning clearly before retrying."
    )

    messages = [SystemMessage(content=REACT_SYSTEM_PROMPT)] + state["messages"] + [
        HumanMessage(content=correction_prompt)
    ]

    llm_with_tools = llm.bind_tools(ALL_TOOLS)
    response = await llm_with_tools.ainvoke(messages)

    return {
        "messages": [response],
        "retry_count": retry_count + 1,
    }

# ── Node: Extraction ────────────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    preferences: list[str]
    title: str

async def extract_preferences_node(state: AgentState) -> dict:
    """Extract user preferences and thread title from the conversation and save to DB."""
    session_id = state.get("session_id", "default")
    messages = state.get("messages", [])
    if len(messages) < 2:
        return {}
    
    # We only want to extract from the recent conversation to save tokens.
    llm = get_llm().with_structured_output(ExtractionResult)
    prompt = (
        "Analyze the following conversation and extract any long-term travel preferences the user has mentioned "
        "(e.g., 'I always prefer aisle seats', 'I only fly Delta airlines'). "
        "Also, provide a short 3-5 word title for the conversation.\n\n"
        f"Conversation:\n" + "\n".join([f"{getattr(msg, 'type', type(msg).__name__)}: {msg.content}" for msg in messages[-5:]])
    )
    
    try:
        result = await llm.ainvoke(prompt)
        prefs = result.preferences
        title = result.title
        
        async with aiosqlite.connect(DB_PATH) as db:
            if prefs:
                cursor = await db.execute("SELECT preferences_json FROM user_preferences WHERE user_id = ?", (session_id,))
                row = await cursor.fetchone()
                existing_prefs = json.loads(row[0]) if row else []
                all_prefs = list(set(existing_prefs + prefs))
                await db.execute(
                    "INSERT INTO user_preferences (user_id, preferences_json) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET preferences_json = ?",
                    (session_id, json.dumps(all_prefs), json.dumps(all_prefs))
                )
            if title:
                await db.execute(
                    "INSERT INTO chat_threads (thread_id, user_id, title) VALUES (?, ?, ?) "
                    "ON CONFLICT(thread_id) DO UPDATE SET title = ?, updated_at = CURRENT_TIMESTAMP",
                    (session_id, session_id, title, title)
                )
            await db.commit()
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error extracting preferences: {e}")
        
    return {}


# ── Routing Functions ────────────────────────────────────────────────────────

def should_use_tools(state: AgentState) -> str:
    """Route: does the agent want to call tools?"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"


def should_correct(state: AgentState) -> str:
    """Route: did tools fail and do we have retries left?"""
    tool_results = state.get("tool_results", [])
    retry_count = state.get("retry_count", 0)

    has_errors = any("error" in r for r in tool_results)
    can_retry = retry_count < MAX_RETRIES

    if has_errors and can_retry:
        return "self_correction"
    return "agent"  # proceed to next agent turn regardless
