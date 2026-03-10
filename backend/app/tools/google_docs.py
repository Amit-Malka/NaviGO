"""Google Docs Tool — creates a formatted trip itinerary document."""
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from langchain_core.tools import tool
import json


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


def _get_docs_service(token: dict):
    return build("docs", "v1", credentials=_build_credentials(token))


def _get_drive_service(token: dict):
    return build("drive", "v3", credentials=_build_credentials(token))


def _trim_flights(flights_json: str, max_results: int = 3) -> str:
    """Keep only the first `max_results` flights and strip verbose fields.

    This prevents the LLM from having to serialize a huge payload into the
    tool call, which would eat into the model's token rate limit.
    """
    try:
        if isinstance(flights_json, str):
            flight_list = json.loads(flights_json)
        else:
            flight_list = flights_json
        
        # If it's a dict (e.g. LLM wrapped in a key), try to find a list value
        if isinstance(flight_list, dict):
            for v in flight_list.values():
                if isinstance(v, list):
                    flight_list = v
                    break
                    
        if not isinstance(flight_list, list):
            flight_list = [flight_list] if flight_list else []
            
        trimmed = []
        for f in flight_list[:max_results]:
            if not isinstance(f, dict):
                continue
            legs = f.get("legs", [{}])
            leg = legs[0] if legs and isinstance(legs, list) else {}
            trimmed.append({
                "airline_code": f.get("airline_code", "?"),
                "price": f.get("price", "?"),
                "duration": leg.get("duration", "?") if isinstance(leg, dict) else "?",
                "stops": leg.get("stops", "?") if isinstance(leg, dict) else "?",
            })
        return json.dumps(trimmed)
    except Exception:
        # If it's not valid JSON or parsing fails, return as-is
        return flights_json if isinstance(flights_json, str) else str(flights_json)


from pydantic import Field
from langchain_core.runnables.config import RunnableConfig
from typing import Annotated

@tool
def create_trip_document(
    destination: Annotated[str, Field(description="Trip destination city/country")],
    origin: Annotated[str, Field(description="Trip origin city/country")],
    departure_date: Annotated[str, Field(description="Departure date string")],
    adults: Annotated[int, Field(description="Number of travelers")],
    flights: Annotated[str, Field(description="JSON string of flight options from Amadeus (top 3 results)")],
    config: RunnableConfig,
    return_date: Annotated[str, Field(description="Return date string (leave empty for one-way trips)")] = "",
    preferences: Annotated[str, Field(description="User's travel preferences")] = "",
) -> dict:
    """Create a Google Docs trip itinerary document.
    Only call this after explicit user confirmation.

    Args:
        destination: Trip destination city/country
        origin: Trip origin city/country
        departure_date: Departure date string
        return_date: Return date string
        adults: Number of travelers
        flights: JSON string of flight options from Amadeus (top 3 results)
        preferences: User's travel preferences
    Returns doc URL and ID on success.
    """
    try:
        conf = config.get("configurable", {}) if config else {}
        token = conf.get("google_token", {})
        if not token:
            return {"error": "Google authentication required. Please connect your Google account in the sidebar."}

        docs = _get_docs_service(token)
        drive = _get_drive_service(token)

        title = f"✈️ NaviGO Trip: {origin} → {destination} ({departure_date})"
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        # Trim flight data so the doc stays readable regardless of how the LLM serialized it
        flights_trimmed = _trim_flights(flights)

        # Parse flights for display
        flight_text = ""
        try:
            if isinstance(flights_trimmed, str):
                flight_list = json.loads(flights_trimmed)
            else:
                flight_list = flights_trimmed
                
            if isinstance(flight_list, dict):
                for v in flight_list.values():
                    if isinstance(v, list):
                        flight_list = v
                        break
                        
            if not isinstance(flight_list, list):
                flight_list = [flight_list] if flight_list else []
                
            for i, f in enumerate(flight_list, 1):
                if not isinstance(f, dict):
                    continue
                flight_text += (
                    f"Option {i}: {f.get('airline_code', '?')} | "
                    f"{f.get('price', '?')} | "
                    f"Duration: {f.get('duration', '?')} | "
                    f"Stops: {f.get('stops', '?')}\n"
                )
        except Exception:
            flight_text = flights if isinstance(flights, str) else str(flights)

        body_text = (
            f"🌍 TRIP ITINERARY\n"
            f"Generated by NaviGO AI Travel Agent\n\n"
            f"TRIP DETAILS\n"
            f"• Origin: {origin}\n"
            f"• Destination: {destination}\n"
            f"• Departure: {departure_date}\n"
            f"• Return: {return_date or 'N/A (One-way)'}\n"
            f"• Travelers: {adults} adult(s)\n"
            f"• Preferences: {preferences or 'None specified'}\n\n"
            f"FLIGHT OPTIONS\n"
            f"{flight_text or 'No flight data available'}\n\n"
            f"SUGGESTED ITINERARY\n"
            f"• Day 1: Arrive in {destination}, check in & explore\n"
            f"• Day 2-N: Explore local attractions\n"
            f"• Last Day: Return flight from {destination}\n\n"
            f"TIPS\n"
            f"• Book accommodation in advance\n"
            f"• Check visa requirements for your passport\n"
            f"• Travel insurance is recommended\n"
        )

        requests = [{
            "insertText": {
                "location": {"index": 1},
                "text": body_text,
            }
        }]
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests},
        ).execute()

        # Make shareable
        drive.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return {"success": True, "doc_url": doc_url, "doc_id": doc_id, "title": title}

    except Exception as e:
        return {"error": f"Failed to create document: {str(e)}"}
