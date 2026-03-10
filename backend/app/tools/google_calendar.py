"""Google Calendar Tool — creates a calendar event for the trip."""
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from langchain_core.tools import tool


def _build_credentials(token: dict) -> Credentials:
    """Build (and refresh if needed) a Google Credentials object from the token dict."""
    expiry = None
    raw_expiry = token.get("expiry")
    if raw_expiry:
        try:
            expiry = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
        except Exception:
            expiry = None

    creds = Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri=token.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=token.get("client_id"),
        client_secret=token.get("client_secret"),
        scopes=token.get("scopes"),
        expiry=expiry,
    )
    # Refresh proactively if expired, invalid, or legacy token payload has no expiry.
    should_refresh = bool(creds.refresh_token) and (
        creds.expired or not creds.valid or creds.expiry is None
    )
    if should_refresh:
        creds.refresh(GoogleAuthRequest())
        token["access_token"] = creds.token
        token["expiry"] = creds.expiry.isoformat() if creds.expiry else None
        token["scopes"] = creds.scopes or token.get("scopes")
    return creds


def _get_calendar_service(token: dict):
    return build("calendar", "v3", credentials=_build_credentials(token))


from pydantic import Field
from langchain_core.runnables.config import RunnableConfig
from typing import Annotated

@tool
def create_calendar_event(
    destination: Annotated[str, Field(description="Trip destination")],
    origin: Annotated[str, Field(description="Origin city")],
    departure_date: Annotated[str, Field(description="Departure date in YYYY-MM-DD format")],
    config: RunnableConfig,
    return_date: Annotated[str, Field(description="Return date in YYYY-MM-DD format (leave empty for one-way trips)")] = "",
    doc_url: Annotated[str, Field(description="URL of the trip's Google Doc")] = "",
    notes: Annotated[str, Field(description="Any extra notes for the event description")] = "",
) -> dict:
    """Create a Google Calendar event for the trip.
    Only call this after the Google Doc has been successfully created.

    Args:
        destination: Trip destination
        origin: Origin city
        departure_date: Departure date in YYYY-MM-DD format
        return_date: Return date in YYYY-MM-DD format
        doc_url: URL of the trip's Google Doc (from create_trip_document)
        notes: Any extra notes for the event description
    Returns event URL on success.
    """
    try:
        conf = config.get("configurable", {}) if config else {}
        token = conf.get("google_token", {})
        if not token:
            return {"error": "Google authentication required. Please connect your Google account in the sidebar."}

        service = _get_calendar_service(token)

        description = (
            f"✈️ Trip planned by NaviGO AI Travel Agent\n\n"
            f"Route: {origin} → {destination} → {origin}\n"
        )
        if doc_url:
            description += f"\n📄 Full Itinerary: {doc_url}\n"
        if notes:
            description += f"\n📝 Notes: {notes}\n"
        description += "\nSafe travels! 🌍"

        # If no return date (one-way trip), make the event 1 day long
        end_date = return_date
        try:
            from datetime import datetime, timedelta
            if end_date:
                # Multi-day trip: Google Calendar API requires the all-day end date
                # to be exclusive (the day *after* the trip ends).
                dt = datetime.strptime(end_date, "%Y-%m-%d")
                end_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # One-way trip: Ends the day after departure
                dt = datetime.strptime(departure_date, "%Y-%m-%d")
                end_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            # Fallback if parsing fails
            end_date = return_date if return_date else departure_date

        event = {
            "summary": f"✈️ Trip to {destination}",
            "description": description,
            "start": {"date": departure_date},
            "end": {"date": end_date},
            "colorId": "7",  # teal/peacock
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60 * 24 * 3},    # 3 days before
                    {"method": "popup", "minutes": 60 * 24},         # 1 day before
                    {"method": "email", "minutes": 60 * 24 * 7},     # 1 week before
                ],
            },
        }

        created = service.events().insert(calendarId="primary", body=event).execute()
        event_url = created.get("htmlLink", "")

        return {
            "success": True,
            "event_url": event_url,
            "event_id": created.get("id"),
            "summary": event["summary"],
        }

    except Exception as e:
        return {"error": f"Failed to create calendar event: {str(e)}"}
