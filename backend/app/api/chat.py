"""FastAPI SSE chat endpoint."""
import json
import uuid
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.agent.graph import create_graph_with_memory
from app.config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    google_token: dict | None = None


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE streaming endpoint — streams agent tokens + tool events to the frontend."""
    session_id = req.session_id or str(uuid.uuid4())

    graph, saver = await create_graph_with_memory(settings.memory_db_path)

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
        try:
            # Stream the agent graph
            async for event in graph.astream_events(initial_state, config=config, version="v2"):
                # Disconnect check
                if await request.is_disconnected():
                    break

                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                # ── Stream AI text tokens ──────────────────────────────────
                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {
                            "event": "token",
                            "data": json.dumps({"text": chunk.content}),
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

                # ── Self-correction started ────────────────────────────────
                elif kind == "on_chain_start" and name == "self_correction":
                    yield {
                        "event": "self_correction",
                        "data": json.dumps({"message": "Detected an issue, trying a different approach..."}),
                    }

            # ── Session ID for frontend to persist ────────────────────────
            yield {
                "event": "done",
                "data": json.dumps({"session_id": session_id}),
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }
        finally:
            await saver.conn.close() if hasattr(saver, "conn") else None

    return EventSourceResponse(event_generator())


@router.get("/session/{session_id}/history")
async def get_history(session_id: str):
    """Retrieve chat history for a session (for memory display)."""
    graph, saver = await create_graph_with_memory(settings.memory_db_path)
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
