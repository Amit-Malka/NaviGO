# NaviGO - Agentic AI Travel Assistant

NaviGO is a full-stack AI travel agent.
It uses a LangGraph-based reasoning loop, executes real external tools, retries on failures, and persists user preferences across sessions.

## Requirements Coverage

### Core Requirements

| Requirement | Status | Evidence in Code |
|---|---|---|
| Agentic logic (reason, plan, act) | Implemented | `backend/app/agent/graph.py` wires `agent -> tools -> self_correction -> tools/agent -> end`; `backend/app/agent/prompts.py` instructs a short user-facing plan before tool execution. |
| At least 2 external tools | Implemented (6 tools) | `backend/app/agent/nodes.py` binds Amadeus, ADSBDB, Google Docs, Google Calendar tools. |
| Self-correction on tool failure | Implemented | `should_correct()` routes failed tool calls to `self_correction_node()` with retries (`MAX_RETRIES = 2`). |

### Nice-to-Haves

| Feature | Status | Evidence in Code |
|---|---|---|
| Long-term memory across sessions | Implemented | SQLite checkpointer (`AsyncSqliteSaver`) + preference tables in `backend/app/db.py`; retrieval/injection in `backend/app/agent/nodes.py`. |
| Modern UI ("vibe-coded") | Implemented | React + Vite app with themed interface, streaming chat, tool activity badges, and session history in `frontend/src/App.tsx` + CSS. |

## System Architecture

```
Frontend (React + Vite)
  -> POST /api/chat/stream (SSE)
Backend (FastAPI)
  -> LangGraph StateGraph agent
      -> LLM (Groq, model via GROQ_MODEL)
      -> Tools:
         - Amadeus Flights
         - ADSBDB Aircraft Lookup
         - Google Docs
         - Google Calendar
  -> SQLite (chat threads, preference facts, LangGraph checkpoints)
```

## Agent Flow

1. User message enters `agent_node` (reasoning + tool selection).
2. If tool calls are present, `tool_node` executes them and appends tool outputs.
3. If any tool fails, graph routes to `self_correction_node` and retries.
4. If no more tool work is needed, `extract_preferences_node` stores long-term preferences and a thread title.
5. Response streams to the UI token-by-token via SSE, including tool start/end and correction events.

## Tools

- `search_flights` (Amadeus): real flight offers with structured options.
- `search_airport_by_city` (Amadeus): resolves city names to IATA codes (used for correction).
- `search_aircraft_by_callsign` (ADSBDB): enriches route with aircraft/operator details.
- `search_aircraft_by_registration` (ADSBDB): aircraft details by tail number.
- `create_trip_document` (Google Docs): generates a full itinerary document.
- `create_calendar_event` (Google Calendar): creates an all-day trip event with reminders.

## Additional External Integrations

- Google Places API and Google Weather API are called internally by `create_trip_document` to enrich destination highlights and weather context.
- These are external API integrations, but not separate LangGraph-callable tools in the current agent graph.

## Self-Correction Strategy

- Tool outputs are normalized as dictionaries with success/error signals.
- Routing logic checks for any `"error"` in tool results.
- On failure, the agent receives an explicit correction prompt with error summary and optional correction hints.
- Example implemented path: invalid IATA code from Amadeus -> use airport lookup tool -> retry flight search.

## Memory Design

- Conversation state is persisted through LangGraph checkpoints keyed by `thread_id`.
- Cross-session preference memory is stored per `user_id` in:
  - `user_preferences`
  - `user_preference_facts`
  - `chat_threads`
- Extracted/inferred preferences are re-injected into system context for future turns.

## Local Setup

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8001
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Environment Variables (Backend)

Required:
- `GROQ_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`

Optional:
- `GROQ_API_KEY_2` (fallback key for rate-limit/function-call recovery)
- `GROQ_MODEL` (default in code: `qwen/qwen3-32b`)
- `GOOGLE_PLACES_API_KEY` (destination highlights/weather in Docs generation)

## Validation Run (Current Repo State)

- Backend tests: `6 passed` (`.venv\Scripts\python.exe -m pytest tests -q` from `backend/`)
- Frontend build: successful (`npm run -s build` from `frontend/`)

## Demo Video Checklist

Use this order to satisfy the deliverable clearly:

1. Ask for a multi-step trip task (origin, destination, dates, preferences).
2. Show the agent plan and tool calls in-stream.
3. Trigger a correction case (city instead of IATA, then corrected retry).
4. Confirm and create Google Doc itinerary.
5. Confirm and create Google Calendar event.
6. Start a new session and show memory-based preference recall.

## Notes

- OAuth tokens are kept in in-memory stores in `auth.py` (acceptable for demo, not production).
- Session identity uses JWT cookies for anonymous and Google-authenticated users.
