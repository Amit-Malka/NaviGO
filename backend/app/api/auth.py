"""Google OAuth2 endpoints."""
from fastapi import APIRouter, Request
from google_auth_oauthlib.flow import Flow

from app.config import settings
from app.session_auth import create_session_token, get_user_id_from_request, set_session_cookie

router = APIRouter(prefix="/api/auth", tags=["auth"])

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
    "openid",
    "email",
]

# In-memory token stores (production should use Redis/DB).
_token_store_by_session: dict[str, dict] = {}
_token_store_by_user: dict[str, dict] = {}


def get_token_for_session(session_id: str) -> dict | None:
    """Return token for a session if present."""
    return _token_store_by_session.get(session_id)


def get_token_for_user(user_id: str) -> dict | None:
    """Return token for a signed-in user if present."""
    return _token_store_by_user.get(user_id)


def _make_flow() -> Flow:
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )


@router.get("/google")
async def google_auth(session_id: str):
    """Return Google OAuth consent URL."""
    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        state=session_id,
        prompt="consent",
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def google_callback(code: str, state: str):
    """Handle OAuth callback, persist token, and set JWT identity cookie."""
    from fastapi.responses import HTMLResponse
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token as google_id_token
    import json as _json
    import os
    import traceback

    # google-auth-oauthlib raises ScopeChanged when Google returns a superset
    # of the requested scopes (e.g. drive instead of drive.file). Relax this.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    flow = _make_flow()
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        previous_token = _token_store_by_session.get(state, {})
        token_data = {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token or previous_token.get("refresh_token"),
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": credentials.scopes or SCOPES,
            "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        }
        _token_store_by_session[state] = token_data

        google_sub: str | None = None
        email: str | None = None
        try:
            if credentials.id_token:
                id_info = google_id_token.verify_oauth2_token(
                    credentials.id_token,
                    GoogleRequest(),
                    settings.google_client_id,
                )
                google_sub = id_info.get("sub")
                email = id_info.get("email")
        except Exception as id_err:
            print(f"[OAuth callback] id_token verification failed: {id_err}")

        user_id: str | None = None
        session_cookie: str | None = None
        if google_sub:
            user_id = f"google:{google_sub}"
            _token_store_by_user[user_id] = token_data
            session_cookie = create_session_token(user_id=user_id, provider="google", email=email)

        payload = _json.dumps({"type": "navigo-auth-success", "token": token_data, "user_id": user_id})
        html = f"""<!DOCTYPE html><html><body><script>
  try {{
    window.opener.postMessage({payload}, '*');
  }} catch(e) {{}}
  window.close();
</script><p>Authentication successful. You can close this window.</p></body></html>"""
        response = HTMLResponse(content=html)
        if session_cookie:
            set_session_cookie(response, session_cookie)
        return response

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[OAuth callback error]\n{tb}")
        error_html = f"""<!DOCTYPE html><html><body><script>
  try {{
    window.opener.postMessage({{type:'navigo-auth-error', message:{_json.dumps(str(e))}}}, '*');
  }} catch(e) {{}}
  window.close();
</script><p>Authentication failed: {e}</p><pre style="font-size:11px">{tb}</pre></body></html>"""
        return HTMLResponse(content=error_html, status_code=400)


@router.get("/token/{session_id}")
async def get_token(session_id: str):
    """Frontend polls this to retrieve the stored token after OAuth callback."""
    token = _token_store_by_session.get(session_id)
    if not token:
        return {"status": "pending", "token": None}
    return {"token": token}


@router.delete("/token/{session_id}")
async def revoke_token(session_id: str):
    """Remove the stored token for a session."""
    _token_store_by_session.pop(session_id, None)
    return {"status": "revoked"}


@router.get("/me")
async def whoami(request: Request):
    """Return authenticated identity from JWT session cookie, if available."""
    user_id = get_user_id_from_request(request)
    return {"user_id": user_id}

