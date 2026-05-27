"""Central in-memory token registry.

Owns all server-side token stores so that auth.py, chat.py, and nodes.py
can all import from here without creating circular dependencies.

Note: these dicts are process-local and lost on restart.
A persistent store (Redis, DB) would be needed for multi-worker deployments.
"""

# session_id -> google OAuth token dict
_google_tokens_by_session: dict[str, dict] = {}

# user_id -> google OAuth token dict  (keyed as "google:{sub}")
_google_tokens_by_user: dict[str, dict] = {}


def set_token_for_session(session_id: str, token: dict) -> None:
    _google_tokens_by_session[session_id] = token


def get_token_for_session(session_id: str) -> dict | None:
    return _google_tokens_by_session.get(session_id)


def delete_token_for_session(session_id: str) -> None:
    _google_tokens_by_session.pop(session_id, None)


def set_token_for_user(user_id: str, token: dict) -> None:
    _google_tokens_by_user[user_id] = token


def get_token_for_user(user_id: str) -> dict | None:
    return _google_tokens_by_user.get(user_id)
