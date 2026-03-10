"""LangGraph ReAct agent nodes."""
import json
import re
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel
import aiosqlite
from langchain_core.runnables.config import RunnableConfig
from app.config import settings
from app.db import DB_PATH
from app.agent.state import AgentState
from app.agent.prompts import REACT_SYSTEM_PROMPT
from app.tools.amadeus_flights import search_flights, search_airport_by_city
from app.tools.adsbdb import search_aircraft_by_callsign, search_aircraft_by_registration
from app.tools.google_docs import create_trip_document
from app.tools.google_calendar import create_calendar_event

# ── LLM Setup ────────────────────────────────────────────────────────────────

def _make_llm(api_key: str) -> ChatGroq:
    return ChatGroq(
        model=settings.groq_model,
        api_key=api_key,
        temperature=0.3,
        streaming=True,
    )

def get_llm() -> ChatGroq:
    """Return LLM using primary key (used by extract_preferences_node which has its own retry)."""
    return _make_llm(settings.groq_api_key)

async def invoke_with_fallback(llm_with_tools, messages: list) -> any:
    """Call the LLM; if key 1 hits a rate-limit or function-call error, retry with key 2.

    This doubles the effective tokens-per-minute budget without any user-visible delay.
    """
    try:
        return await llm_with_tools.ainvoke(messages)
    except Exception as e:
        err_str = str(e).lower()
        is_rate_limit = "rate_limit" in err_str or "429" in err_str
        is_fn_error = "failed to call a function" in err_str or "400" in err_str

        if (is_rate_limit or is_fn_error) and settings.groq_api_key_2:
            print(f"[LLM Fallback] Key 1 failed ({type(e).__name__}), retrying with key 2...")
            # Rebuild the chain with the second key
            llm2 = _make_llm(settings.groq_api_key_2)
            # Re-apply the same tools + tool_choice that were bound to the original chain
            bound = llm2.bind_tools(ALL_TOOLS, tool_choice="auto")
            return await bound.ainvoke(messages)
        raise  # No fallback available or different error — propagate

ALL_TOOLS = [
    search_flights,
    search_airport_by_city,
    search_aircraft_by_callsign,
    search_aircraft_by_registration,
    create_trip_document,
    create_calendar_event,
]

MAX_RETRIES = 2

def _build_preference_fact(
    key: str,
    value: str,
    source: str,
    confidence: float,
    evidence: str,
) -> dict:
    return {
        "pref_key": key,
        "pref_value": value,
        "source": source,
        "confidence": confidence,
        "evidence": evidence[:240],
    }


def _infer_preference_facts_from_text(text: str, source: str = "inferred") -> list[dict]:
    lowered = text.lower()
    facts: list[dict] = []

    if re.search(r"\b(cheapest|lowest price|lowest fare|budget option|most affordable)\b", lowered):
        facts.append(_build_preference_fact(
            "price_priority",
            "cheapest",
            source,
            0.85 if source == "explicit" else 0.75,
            text,
        ))
    if re.search(r"\b(shortest|fastest|quickest|least time)\b", lowered):
        facts.append(_build_preference_fact(
            "time_priority",
            "shortest_duration",
            source,
            0.85 if source == "explicit" else 0.75,
            text,
        ))
    if re.search(r"\b(direct only|nonstop|non-stop|no stops)\b", lowered):
        facts.append(_build_preference_fact(
            "stops_priority",
            "direct_only",
            source,
            0.85 if source == "explicit" else 0.75,
            text,
        ))
    if re.search(r"\b(window seat|aisle seat|middle seat)\b", lowered):
        seat = "window" if "window" in lowered else ("aisle" if "aisle" in lowered else "middle")
        facts.append(_build_preference_fact(
            "seat_preference",
            seat,
            source,
            0.85 if source == "explicit" else 0.75,
            text,
        ))

    return facts


async def _load_preference_context(user_id: str) -> tuple[list[str], list[dict]]:
    legacy_preferences: list[str] = []
    preference_facts: list[dict] = []

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT preferences_json FROM user_preferences WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            raw_preferences = json.loads(row[0])
            legacy_preferences = [p for p in raw_preferences if isinstance(p, str) and p.strip()]

        cursor = await db.execute(
            """
            SELECT pref_key, pref_value, source, confidence, evidence, updated_at
            FROM user_preference_facts
            WHERE user_id = ?
            ORDER BY datetime(updated_at) DESC, confidence DESC
            LIMIT 5
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        for pref_key, pref_value, source, confidence, evidence, updated_at in rows:
            preference_facts.append({
                "pref_key": pref_key,
                "pref_value": pref_value,
                "source": source,
                "confidence": confidence,
                "evidence": evidence,
                "updated_at": updated_at,
            })

    return legacy_preferences, preference_facts


async def _upsert_preference_facts(db, user_id: str, facts: list[dict]) -> None:
    for fact in facts:
        await db.execute(
            """
            INSERT INTO user_preference_facts (user_id, pref_key, pref_value, source, confidence, evidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, pref_key) DO UPDATE SET
                pref_value = excluded.pref_value,
                source = excluded.source,
                confidence = excluded.confidence,
                evidence = excluded.evidence,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                fact["pref_key"],
                fact["pref_value"],
                fact["source"],
                fact["confidence"],
                fact["evidence"],
            ),
        )

# ── Node: Agent (Reasoning + Planning) ───────────────────────────────────────

async def agent_node(state: AgentState) -> dict:
    """Main ReAct reasoning node. The LLM thinks, plans, and decides tool calls."""
    llm = get_llm()
    # tool_choice="auto" is required for qwen/qwen3-32b to reliably
    # format function calls. Without it, Groq can return a 'Failed to call a function' error.
    llm_with_tools = llm.bind_tools(ALL_TOOLS, tool_choice="auto")

    # Truncate history to the last 12 messages to prevent context bloat.
    # Long histories with many tool results push tokens over Groq's rate limit
    # and cause malformed function call generation.
    recent_messages = state["messages"][-12:]
    messages = [SystemMessage(content=REACT_SYSTEM_PROMPT)] + recent_messages

    # Inject context
    user_id = state.get("user_id") or state.get("session_id", "default")
    preferences: list[str] = []
    preference_facts: list[dict] = []
    try:
        preferences, preference_facts = await _load_preference_context(user_id)
    except Exception as e:
        print(f"Error fetching preferences: {e}")

    context = ""
    if state.get("trip_info"):
        context += f"\n\n[Current trip info extracted so far: {json.dumps(state['trip_info'])}]"
    if preference_facts:
        compact_facts = [
            {
                "key": f["pref_key"],
                "value": f["pref_value"],
                "source": f["source"],
                "confidence": f["confidence"],
            }
            for f in preference_facts
        ]
        context += f"\n\n[Persistent user preference memory: {json.dumps(compact_facts)}]"
    if preferences:
        context += f"\n\n[Additional past preferences: {json.dumps(preferences)}]"
    if any(
        f["pref_key"] == "price_priority" and f["pref_value"] == "cheapest"
        for f in preference_facts
    ):
        context += "\n\n[Behavior hint: prioritize lower-priced flight options first unless the user asks otherwise.]"

    if context:
        messages[0] = SystemMessage(content=REACT_SYSTEM_PROMPT + context)

    response = await invoke_with_fallback(llm_with_tools, messages)
    return {"messages": [response]}


# ── Node: Tool Executor ───────────────────────────────────────────────────────

async def tool_node(state: AgentState, config: RunnableConfig) -> dict:
    """Execute all tool calls from the last AI message."""
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    # Get google_token from the server-side store (keyed by session_id).
    # We cannot use config["configurable"]["google_token"] because LangGraph's
    # AsyncSqliteSaver strips non-checkpoint keys from configurable internally.
    from app.api.chat import get_google_token_for_session
    session_id = state.get("session_id", "")
    google_token = get_google_token_for_session(session_id)
    # DEBUG — remove once confirmed working
    print(f"[DEBUG tool_node] session={session_id[:8] if session_id else '?'} google_token_present={bool(google_token)}")

    tool_map = {t.name: t for t in ALL_TOOLS}
    results = []
    tool_messages = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = dict(tool_call["args"])  # Copy to avoid mutating AIMessage history
        tool_id = tool_call["id"]

        tool_fn = tool_map.get(tool_name)
        if not tool_fn:
            result = {"error": f"Unknown tool: {tool_name}"}
        else:
            try:
                # Pass google_token via configurable so InjectedToolArg picks it up
                run_config = {"configurable": {"google_token": google_token}}
                if hasattr(tool_fn, "ainvoke"):
                    result = await tool_fn.ainvoke(tool_args, config=run_config)
                else:
                    result = tool_fn.invoke(tool_args, config=run_config)

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
    # Use a lightweight LLM call (no tool binding) just to craft a correction message.
    # The corrected message goes back to agent_node which will re-bind tools properly.
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

    # Bind tools so the corrected response can issue new tool calls
    llm_with_tools = llm.bind_tools(ALL_TOOLS, tool_choice="auto")
    response = await invoke_with_fallback(llm_with_tools, messages)

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
    user_id = state.get("user_id") or session_id
    messages = state.get("messages", [])
    if len(messages) < 2:
        return {}
    
    # No tool binding here — this node only does structured output extraction.
    # Binding tools wastes ~1,500 tokens against the rate limit for no benefit.
    llm = get_llm().with_structured_output(ExtractionResult)
    prompt = (
        "Analyze the following conversation and extract any long-term travel preferences the user has mentioned "
        "(e.g., 'I always prefer aisle seats', 'I only fly Delta airlines'). "
        "Also, provide a short 3-5 word title for the conversation.\n\n"
        f"Conversation:\n" + "\n".join([f"{getattr(msg, 'type', type(msg).__name__)}: {msg.content}" for msg in messages[-5:]])
    )
    
    try:
        result = await llm.ainvoke(prompt)
        prefs = [p.strip() for p in (result.preferences or []) if isinstance(p, str) and p.strip()]
        title = result.title or ""

        inferred_facts: list[dict] = []
        for pref in prefs:
            inferred_facts.extend(_infer_preference_facts_from_text(pref, source="explicit"))

        for msg in messages[-8:]:
            if isinstance(msg, HumanMessage) and getattr(msg, "content", None):
                inferred_facts.extend(_infer_preference_facts_from_text(str(msg.content), source="inferred"))

        facts_by_key: dict[str, dict] = {}
        for fact in inferred_facts:
            existing = facts_by_key.get(fact["pref_key"])
            if not existing or fact["confidence"] >= existing["confidence"]:
                facts_by_key[fact["pref_key"]] = fact
        deduped_facts = list(facts_by_key.values())
        
        async with aiosqlite.connect(DB_PATH) as db:
            if prefs:
                cursor = await db.execute("SELECT preferences_json FROM user_preferences WHERE user_id = ?", (user_id,))
                row = await cursor.fetchone()
                raw_existing = json.loads(row[0]) if row else []
                existing_prefs = [p for p in raw_existing if isinstance(p, str) and p.strip()]
                all_prefs = sorted(set(existing_prefs + prefs))
                await db.execute(
                    "INSERT INTO user_preferences (user_id, preferences_json) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET preferences_json = ?",
                    (user_id, json.dumps(all_prefs), json.dumps(all_prefs))
                )
            if deduped_facts:
                await _upsert_preference_facts(db, user_id, deduped_facts)
            if title:
                await db.execute(
                    "INSERT INTO chat_threads (thread_id, user_id, title) VALUES (?, ?, ?) "
                    "ON CONFLICT(thread_id) DO UPDATE SET title = ?, updated_at = CURRENT_TIMESTAMP",
                    (session_id, user_id, title, title)
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
