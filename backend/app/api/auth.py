"""Google OAuth2 endpoints."""
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
    "openid",
    "email",
]

# In-memory token store (production would use Redis/DB)
_token_store: dict[str, dict] = {}


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
    """Redirect user to Google's OAuth consent screen."""
    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=session_id,
        prompt="consent",
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def google_callback(code: str, state: str):
    """Handle OAuth callback — exchange code for token, then close the popup via postMessage."""
    from fastapi.responses import HTMLResponse
    import json as _json
    import os, traceback

    # google-auth-oauthlib raises ScopeChanged when Google returns a superset
    # of the requested scopes (e.g. drive instead of drive.file). Relax this.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    flow = _make_flow()
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        token_data = {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        }
        _token_store[state] = token_data

        payload = _json.dumps({"type": "navigo-auth-success", "token": token_data})
        html = f"""<!DOCTYPE html><html><body><script>
  try {{
    window.opener.postMessage({payload}, '*');
  }} catch(e) {{}}
  window.close();
</script><p>Authentication successful. You can close this window.</p></body></html>"""
        return HTMLResponse(content=html)

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
    token = _token_store.get(session_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found or expired")
    return {"token": token}


@router.delete("/token/{session_id}")
async def revoke_token(session_id: str):
    """Remove the stored token for a session."""
    _token_store.pop(session_id, None)
    return {"status": "revoked"}
