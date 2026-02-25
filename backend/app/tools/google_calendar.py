"""Google Calendar Tool — creates a calendar event for the trip."""
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from langchain_core.tools import tool
import json


def _get_calendar_service(token: dict):
    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token.get("client_id"),
        client_secret=token.get("client_secret"),
    )
    return build("calendar", "v3", credentials=creds)


@tool
def create_calendar_event(
    google_token_json: str,
    destination: str,
    origin: str,
    departure_date: str,
    return_date: str,
    doc_url: str = "",
    notes: str = "",
) -> dict:
    """Create a Google Calendar event for the trip.
    Only call this after the Google Doc has been successfully created.

    Args:
        google_token_json: JSON string of the user's Google OAuth token
        destination: Trip destination
        origin: Origin city
        departure_date: Departure date in YYYY-MM-DD format
        return_date: Return date in YYYY-MM-DD format
        doc_url: URL of the trip's Google Doc (from create_trip_document)
        notes: Any extra notes for the event description
    Returns event URL on success.
    """
    try:
        token = json.loads(google_token_json)
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

        event = {
            "summary": f"✈️ Trip to {destination}",
            "description": description,
            "start": {"date": departure_date},
            "end": {"date": return_date},
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
