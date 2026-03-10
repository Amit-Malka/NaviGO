from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class TripInfo(TypedDict, total=False):
    """Structured trip details extracted during dialogue."""
    origin: str
    destination: str
    departure_date: str
    return_date: str
    adults: int
    budget: str
    preferences: list[str]
    airline_preference: str


class AgentState(TypedDict):
    # Conversation messages (append-only)
    messages: Annotated[list, add_messages]
    # Structured trip info extracted so far
    trip_info: TripInfo
    # Results from the last tool call
    tool_results: list[dict[str, Any]]
    # The agent's current plan (list of step strings)
    plan_steps: list[str]
    # How many correction retries have been attempted on this step
    retry_count: int
    # Google OAuth token (set after user grants permission)
    google_token: dict[str, Any] | None
    # Session ID (for memory checkpointing)
    session_id: str
    # Stable user ID (for cross-session preference memory)
    user_id: str
    # Whether the user has approved Docs + Calendar creation
    user_confirmed_creation: bool
