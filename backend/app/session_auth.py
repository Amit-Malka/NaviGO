"""JWT-backed session identity helpers."""
from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
from fastapi import Request, Response

from app.config import settings

SESSION_COOKIE_NAME = "navigo_session"


def _ttl_seconds() -> int:
    return max(1, settings.session_jwt_ttl_hours) * 3600


def create_session_token(user_id: str, provider: str = "anon", email: str | None = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "provider": provider,
        "iat": now,
        "exp": now + _ttl_seconds(),
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, settings.session_jwt_secret, algorithm=settings.session_jwt_algorithm)


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            settings.session_jwt_secret,
            algorithms=[settings.session_jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    return payload


def get_user_id_from_request(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    payload = decode_session_token(token)
    if not payload:
        return None
    return payload["sub"]


def resolve_or_create_user_session(request: Request) -> tuple[str, str | None]:
    user_id = get_user_id_from_request(request)
    if user_id:
        return user_id, None

    user_id = f"anon:{uuid.uuid4()}"
    token = create_session_token(user_id=user_id, provider="anon")
    return user_id, token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_ttl_seconds(),
        httponly=True,
        secure=False,  # Local dev over HTTP
        samesite="lax",
        path="/",
    )

