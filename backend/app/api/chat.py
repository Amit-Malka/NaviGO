"""FastAPI SSE chat endpoint."""
import json
import uuid
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage
from app.agent.graph import get_graph_with_memory
from app.config import settings  # noqa: F401 — imported for side-effects (loads .env)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Module-level graph — shared across requests, MemorySaver persists state
# per thread_id. Created once on first request.
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = get_graph_with_memory()
    return _graph


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    google_token: dict | None = None


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE streaming endpoint — streams agent tokens + tool events to the frontend."""
    session_id = req.session_id or str(uuid.uuid4())
    graph = _get_graph()

    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 20,
    }

    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "trip_info": {},
        "tool_results": [],
        "plan_steps": [],
        "retry_count": 0,
        "google_token": req.google_token,
        "session_id": session_id,
        "user_confirmed_creation": False,
    }

    async def event_generator():
        # Track whether any tokens were streamed so we can send final_text fallback
        streamed_text = []

        try:
            async for event in graph.astream_events(initial_state, config=config, version="v2"):
                if await request.is_disconnected():
                    break

                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                # ── Stream AI text tokens ──────────────────────────────────
                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        streamed_text.append(chunk.content)
                        yield {
                            "event": "token",
                            "data": json.dumps({"text": chunk.content}),
                        }

                # ── Capture final AI message if not already streamed ───────
                elif kind == "on_chain_end" and name == "agent":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        messages = output.get("messages", [])
                        if messages and not streamed_text:
                            last = messages[-1]
                            text = getattr(last, "content", "") or ""
                            # Only send if it's a plain text reply (no tool calls)
                            tool_calls = getattr(last, "tool_calls", [])
                            if text and not tool_calls:
                                streamed_text.append(text)
                                # Send as individual tokens so the UI animates
                                for word in text:
                                    yield {
                                        "event": "token",
                                        "data": json.dumps({"text": word}),
                                    }

                # ── Tool start event ───────────────────────────────────────
                elif kind == "on_tool_start":
                    yield {
                        "event": "tool_start",
                        "data": json.dumps({
                            "tool": name,
                            "input": data.get("input", {}),
                        }),
                    }

                # ── Tool end event ─────────────────────────────────────────
                elif kind == "on_tool_end":
                    output = data.get("output", {})
                    if hasattr(output, "content"):
                        output = output.content
                    yield {
                        "event": "tool_end",
                        "data": json.dumps({
                            "tool": name,
                            "output": output,
                            "success": "error" not in str(output).lower(),
                        }),
                    }

                # ── Self-correction ────────────────────────────────────────
                elif kind == "on_chain_start" and name == "self_correction":
                    yield {
                        "event": "self_correction",
                        "data": json.dumps({"message": "Working on it.."}),
                    }

            # Done — also send final_text so frontend has it as fallback
            yield {
                "event": "done",
                "data": json.dumps({
                    "session_id": session_id,
                    "final_text": "".join(streamed_text),
                }),
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.get("/sessions")
async def get_sessions():
    """Retrieve all chat sessions for the sidebar."""
    from app.db import DB_PATH
    import aiosqlite
    from fastapi import HTTPException
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT thread_id, title, updated_at FROM chat_threads ORDER BY updated_at DESC")
            rows = await cursor.fetchall()
            sessions = [{"id": row["thread_id"], "title": row["title"], "updated_at": row["updated_at"]} for row in rows]
            return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/session/{session_id}/history")
async def get_history(session_id: str):
    """Retrieve chat history for a session (for memory display)."""
    from fastapi import HTTPException
    graph = _get_graph()
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await graph.aget_state(config)
        messages = state.values.get("messages", []) if state else []
        history = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content or ""})
        return {"session_id": session_id, "history": history}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
