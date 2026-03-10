"""FastAPI SSE chat endpoint."""
import json
import uuid

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import get_graph_with_memory
from app.db import DB_PATH
from app.session_auth import resolve_or_create_user_session, set_session_cookie

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Module-level graph: shared across requests, MemorySaver persists state per thread_id.
_graph = None

# Server-side token store: session_id -> google_token dict.
# This bypasses LangGraph's config pipeline which strips unknown configurable keys.
_google_token_store: dict[str, dict] = {}


def get_google_token_for_session(session_id: str) -> dict | None:
    """Called by tool_node to retrieve the google_token for the current session."""
    return _google_token_store.get(session_id)


def _get_graph():
    global _graph
    if _graph is None:
        _graph = get_graph_with_memory()
    return _graph


async def _ensure_session_owner(session_id: str, user_id: str) -> str:
    """Ensure thread ownership. If session belongs to another user, return a new session id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT user_id FROM chat_threads WHERE thread_id = ?", (session_id,))
        row = await cursor.fetchone()

        if row and row["user_id"] and row["user_id"] != user_id:
            return str(uuid.uuid4())

        await db.execute(
            "INSERT OR IGNORE INTO chat_threads (thread_id, user_id, title) VALUES (?, ?, ?)",
            (session_id, user_id, "Untitled Trip"),
        )
        await db.commit()
    return session_id


async def _user_owns_session(session_id: str, user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT 1 FROM chat_threads WHERE thread_id = ? AND user_id = ? LIMIT 1",
            (session_id, user_id),
        )
        return await cursor.fetchone() is not None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    google_token: dict | None = None


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE streaming endpoint: streams agent tokens + tool events to frontend."""
    user_id, issued_session_cookie = resolve_or_create_user_session(request)
    requested_session_id = req.session_id or str(uuid.uuid4())
    session_id = await _ensure_session_owner(requested_session_id, user_id)
    graph = _get_graph()

    # Store google_token server-side keyed by session_id.
    # LangGraph's AsyncSqliteSaver strips non-checkpoint keys from configurable,
    # so we cannot rely on passing it through config["configurable"].
    effective_google_token = req.google_token
    if not effective_google_token:
        from app.api.auth import get_token_for_session, get_token_for_user

        effective_google_token = get_token_for_session(session_id) or get_token_for_user(user_id)
    if effective_google_token:
        _google_token_store[session_id] = effective_google_token

    config = {
        "configurable": {
            "thread_id": session_id,
        },
        "recursion_limit": 20,
    }
    has_token = bool(effective_google_token and effective_google_token.get("access_token"))
    stored = bool(_google_token_store.get(session_id))
    print(f"[DEBUG chat.py] session={session_id[:8]} token_in_request={has_token} token_in_store={stored}")

    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "trip_info": {},
        "tool_results": [],
        "plan_steps": [],
        "retry_count": 0,
        "google_token": effective_google_token,
        "session_id": session_id,
        "user_id": user_id,
        "user_confirmed_creation": False,
    }

    async def event_generator():
        streamed_text = []
        try:
            async for event in graph.astream_events(initial_state, config=config, version="v2"):
                if await request.is_disconnected():
                    break

                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        streamed_text.append(chunk.content)
                        yield {
                            "event": "token",
                            "data": json.dumps({"text": chunk.content}),
                        }
                elif kind == "on_chain_end" and name == "agent":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        messages = output.get("messages", [])
                        if messages and not streamed_text:
                            last = messages[-1]
                            text = getattr(last, "content", "") or ""
                            tool_calls = getattr(last, "tool_calls", [])
                            if text and not tool_calls:
                                streamed_text.append(text)
                                for char in text:
                                    yield {
                                        "event": "token",
                                        "data": json.dumps({"text": char}),
                                    }
                elif kind == "on_tool_start":
                    yield {
                        "event": "tool_start",
                        "data": json.dumps(
                            {
                                "tool": name,
                                "input": data.get("input", {}),
                            }
                        ),
                    }
                elif kind == "on_tool_end":
                    output = data.get("output", {})
                    if hasattr(output, "content"):
                        output = output.content
                    yield {
                        "event": "tool_end",
                        "data": json.dumps(
                            {
                                "tool": name,
                                "output": output,
                                "success": "error" not in str(output).lower(),
                            }
                        ),
                    }
                elif kind == "on_chain_start" and name == "self_correction":
                    yield {
                        "event": "self_correction",
                        "data": json.dumps({"message": "Working on it.."}),
                    }

            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "session_id": session_id,
                        "final_text": "".join(streamed_text),
                    }
                ),
            }
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            print("STREAM ERROR:", tb)
            yield {
                "event": "error",
                "data": json.dumps({"message": f"{str(e)}\n{tb}"}),
            }

    response = EventSourceResponse(event_generator())
    if issued_session_cookie:
        set_session_cookie(response, issued_session_cookie)
    return response


@router.get("/sessions")
async def get_sessions(request: Request):
    """Retrieve all chat sessions for the current signed-in (or anonymous) user."""
    user_id, issued_session_cookie = resolve_or_create_user_session(request)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT thread_id, title, updated_at FROM chat_threads WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
            sessions = [
                {"id": row["thread_id"], "title": row["title"], "updated_at": row["updated_at"]}
                for row in rows
            ]
            response = JSONResponse(content={"sessions": sessions})
            if issued_session_cookie:
                set_session_cookie(response, issued_session_cookie)
            return response
    except Exception as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/history")
async def get_history(session_id: str, request: Request):
    """Retrieve chat history for a user-owned session."""
    from fastapi import HTTPException

    user_id, issued_session_cookie = resolve_or_create_user_session(request)
    if not await _user_owns_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")

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
        response = JSONResponse(content={"session_id": session_id, "history": history})
        if issued_session_cookie:
            set_session_cookie(response, issued_session_cookie)
        return response
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, request: Request):
    """Delete a user-owned chat session and its checkpointed state."""
    from fastapi import HTTPException

    user_id, issued_session_cookie = resolve_or_create_user_session(request)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT 1 FROM chat_threads WHERE thread_id = ? AND user_id = ? LIMIT 1",
                (session_id, user_id),
            )
            if await cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Session not found")

            await db.execute("DELETE FROM chat_threads WHERE thread_id = ? AND user_id = ?", (session_id, user_id))
            await db.execute("DELETE FROM checkpoints WHERE thread_id = ?", (session_id,))
            await db.execute("DELETE FROM writes WHERE thread_id = ?", (session_id,))
            await db.commit()

        _google_token_store.pop(session_id, None)
        response = JSONResponse(content={"status": "deleted", "session_id": session_id})
        if issued_session_cookie:
            set_session_cookie(response, issued_session_cookie)
        return response
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
