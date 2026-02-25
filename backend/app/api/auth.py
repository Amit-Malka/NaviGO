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
    """Handle OAuth callback — exchange code for token and redirect to frontend."""
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
        # Store token keyed by session_id (the OAuth state param)
        _token_store[state] = token_data

        # Redirect back to frontend with success
        return RedirectResponse(
            url=f"{settings.frontend_url}?auth=success&session_id={state}"
        )
    except Exception as e:
        return RedirectResponse(
            url=f"{settings.frontend_url}?auth=error&message={str(e)}"
        )


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
