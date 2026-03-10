from starlette.requests import Request

from app.session_auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    decode_session_token,
    resolve_or_create_user_session,
)


def _request_with_cookie(cookie_value: str | None = None) -> Request:
    headers = []
    if cookie_value:
        headers.append((b"cookie", f"{SESSION_COOKIE_NAME}={cookie_value}".encode("utf-8")))
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers}
    return Request(scope)


def test_create_and_decode_session_token():
    token = create_session_token("google:abc123", provider="google", email="x@example.com")
    payload = decode_session_token(token)
    assert payload is not None
    assert payload["sub"] == "google:abc123"
    assert payload["provider"] == "google"
    assert payload["email"] == "x@example.com"


def test_resolve_or_create_user_session_without_cookie_creates_anon():
    req = _request_with_cookie()
    user_id, new_token = resolve_or_create_user_session(req)
    assert user_id.startswith("anon:")
    assert new_token is not None
    payload = decode_session_token(new_token)
    assert payload is not None
    assert payload["sub"] == user_id


def test_resolve_or_create_user_session_with_cookie_reuses_identity():
    token = create_session_token("google:xyz", provider="google")
    req = _request_with_cookie(token)
    user_id, new_token = resolve_or_create_user_session(req)
    assert user_id == "google:xyz"
    assert new_token is None

