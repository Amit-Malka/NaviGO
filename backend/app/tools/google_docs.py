"""Google Docs tool - creates a destination-aware trip itinerary document."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math
import re
from typing import Any

import httpx
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from langchain_core.tools import tool
from pydantic import Field
from langchain_core.runnables.config import RunnableConfig
from typing import Annotated

from app.config import settings


def _build_credentials(token: dict) -> Credentials:
    """Build (and refresh if needed) a Google Credentials object from token data."""
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


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _pretty_date(text: str) -> str:
    dt = _parse_date(text)
    return dt.strftime("%b %d, %Y") if dt else text


def _duration_to_minutes(duration: str | None) -> int | None:
    if not duration:
        return None
    s = duration.strip().upper()

    # ISO-8601 style from Amadeus, e.g. PT1H30M
    iso_match = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?$", s)
    if iso_match:
        hours = int(iso_match.group(1) or 0)
        minutes = int(iso_match.group(2) or 0)
        return hours * 60 + minutes

    # Friendly style, e.g. 1h30m / 1h 30m
    friendly_match = re.match(r"^(?:(\d+)\s*H)?\s*(?:(\d+)\s*M)?$", s)
    if friendly_match and (friendly_match.group(1) or friendly_match.group(2)):
        hours = int(friendly_match.group(1) or 0)
        minutes = int(friendly_match.group(2) or 0)
        return hours * 60 + minutes

    return None


def _minutes_to_text(total_minutes: int | None) -> str:
    if total_minutes is None:
        return "N/A"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours == 0:
        return f"{minutes}m"
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"


def _parse_price(price_text: Any) -> float | None:
    if price_text is None:
        return None
    text = str(price_text)
    match = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _extract_flight_list(flights_input: Any) -> list[dict]:
    """Normalize flight payload into a list of flight dictionaries."""
    data = flights_input
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return []

    if isinstance(data, dict):
        if isinstance(data.get("flights"), list):
            return [f for f in data["flights"] if isinstance(f, dict)]
        for value in data.values():
            if isinstance(value, list):
                return [f for f in value if isinstance(f, dict)]
        return [data]

    if isinstance(data, list):
        return [f for f in data if isinstance(f, dict)]

    return []


def _leg_duration_minutes(leg: dict) -> int | None:
    return _duration_to_minutes(str(leg.get("duration", "")))


def _flight_metrics(flight: dict) -> dict[str, Any]:
    legs = flight.get("legs", [])
    if not isinstance(legs, list):
        legs = []

    total_stops = 0
    total_duration = 0
    duration_known = False
    for leg in legs:
        stops = leg.get("stops")
        if isinstance(stops, int):
            total_stops += stops
        minutes = _leg_duration_minutes(leg)
        if minutes is not None:
            duration_known = True
            total_duration += minutes

    if not duration_known:
        total_duration = _duration_to_minutes(str(flight.get("duration", ""))) or 0

    return {
        "price": _parse_price(flight.get("price")),
        "total_stops": total_stops,
        "total_duration_minutes": total_duration if total_duration > 0 else None,
    }


def _format_dt_short(iso_text: str) -> str:
    try:
        return datetime.fromisoformat(iso_text.replace("Z", "+00:00")).strftime("%b %d %H:%M")
    except Exception:
        return iso_text


def _format_stops(stops: Any) -> str:
    if not isinstance(stops, int):
        return "stops: N/A"
    if stops == 0:
        return "nonstop"
    if stops == 1:
        return "1 stop"
    return f"{stops} stops"


def _render_flight_option(index: int, flight: dict) -> list[str]:
    metrics = _flight_metrics(flight)
    airline = flight.get("airline_code", "?")
    price = flight.get("price", "N/A")
    duration = _minutes_to_text(metrics["total_duration_minutes"])

    lines = [
        f"Option {index} - Airline {airline}",
        f"  Price: {price} | Total duration: {duration} | Total stops: {metrics['total_stops']}",
    ]

    legs = flight.get("legs", [])
    if isinstance(legs, list) and legs:
        for leg_idx, leg in enumerate(legs, 1):
            leg_depart = _format_dt_short(str(leg.get("departure", "")))
            leg_arrive = _format_dt_short(str(leg.get("arrival", "")))
            leg_duration = _minutes_to_text(_leg_duration_minutes(leg))
            leg_stops = _format_stops(leg.get("stops"))
            leg_label = "Outbound" if leg_idx == 1 else ("Return" if leg_idx == 2 else f"Leg {leg_idx}")
            lines.append(
                f"  {leg_label}: {leg_depart} -> {leg_arrive} | {leg_duration} | {leg_stops}"
            )

    return lines


def _rank_flights(flights: list[dict], preferences: str) -> list[str]:
    if not flights:
        return ["No ranking available (no flight options found)."]

    scored: list[tuple[int, dict, dict[str, Any]]] = []
    for idx, flight in enumerate(flights, 1):
        scored.append((idx, flight, _flight_metrics(flight)))

    priced = [x for x in scored if x[2]["price"] is not None]
    timed = [x for x in scored if x[2]["total_duration_minutes"] is not None]

    best_value = min(priced, key=lambda x: x[2]["price"]) if priced else None
    fastest = min(timed, key=lambda x: x[2]["total_duration_minutes"]) if timed else None

    pref = (preferences or "").lower()
    wants_direct = any(k in pref for k in ["direct", "nonstop", "non-stop"])
    wants_budget = any(k in pref for k in ["budget", "cheap", "lowest", "affordable"])
    wants_fast = any(k in pref for k in ["fast", "quick", "short", "duration"])

    if wants_direct:
        best_match = min(
            scored,
            key=lambda x: (
                x[2]["total_stops"],
                x[2]["total_duration_minutes"] if x[2]["total_duration_minutes"] is not None else 10**9,
                x[2]["price"] if x[2]["price"] is not None else 10**9,
            ),
        )
    elif wants_budget:
        best_match = min(
            scored,
            key=lambda x: (
                x[2]["price"] if x[2]["price"] is not None else 10**9,
                x[2]["total_duration_minutes"] if x[2]["total_duration_minutes"] is not None else 10**9,
            ),
        )
    elif wants_fast:
        best_match = min(
            scored,
            key=lambda x: (
                x[2]["total_duration_minutes"] if x[2]["total_duration_minutes"] is not None else 10**9,
                x[2]["total_stops"],
                x[2]["price"] if x[2]["price"] is not None else 10**9,
            ),
        )
    else:
        # Balanced score: normalized price + duration + stop penalty
        min_price = min((x[2]["price"] for x in priced), default=1.0)
        min_dur = min((x[2]["total_duration_minutes"] for x in timed), default=1)

        def balanced_score(item: tuple[int, dict, dict[str, Any]]) -> float:
            m = item[2]
            price_part = (m["price"] / min_price) if m["price"] else 3.0
            dur_part = (m["total_duration_minutes"] / min_dur) if m["total_duration_minutes"] else 3.0
            stops_part = 1.0 + (m["total_stops"] * 0.25)
            return price_part + dur_part + stops_part

        best_match = min(scored, key=balanced_score)

    lines = []
    if best_match:
        lines.append(
            f"Best overall match: Option {best_match[0]} "
            f"(price: {best_match[1].get('price', 'N/A')}, "
            f"duration: {_minutes_to_text(best_match[2]['total_duration_minutes'])}, "
            f"stops: {best_match[2]['total_stops']})."
        )
    if best_value:
        lines.append(f"Best value: Option {best_value[0]} ({best_value[1].get('price', 'N/A')}).")
    if fastest:
        lines.append(
            f"Fastest: Option {fastest[0]} "
            f"({_minutes_to_text(fastest[2]['total_duration_minutes'])})."
        )
    return lines


def _clean_destination(destination: str) -> str:
    cleaned = re.sub(r"\([A-Z]{3}\)", "", destination).strip()
    return re.sub(r"\s{2,}", " ", cleaned)


def _places_text_search(api_key: str, query: str, max_results: int = 5) -> list[dict]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.location,"
            "places.rating,places.userRatingCount,places.primaryTypeDisplayName"
        ),
    }
    payload = {"textQuery": query, "maxResultCount": max_results}
    with httpx.Client(timeout=12.0) as client:
        response = client.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json().get("places", []) or []


def _format_place_line(place: dict) -> str:
    name = place.get("displayName", {}).get("text", "Unknown place")
    rating = place.get("rating")
    rating_count = place.get("userRatingCount")
    address = place.get("formattedAddress", "")

    rating_text = ""
    if isinstance(rating, (int, float)):
        if isinstance(rating_count, int):
            rating_text = f" ({rating:.1f}/5, {rating_count} reviews)"
        else:
            rating_text = f" ({rating:.1f}/5)"

    if address:
        return f"- {name}{rating_text} - {address}"
    return f"- {name}{rating_text}"


def _fetch_destination_highlights(destination: str) -> dict[str, Any]:
    """Fetch destination highlights and an approximate center location from Places."""
    api_key = settings.google_places_api_key
    if not api_key:
        return {
            "city": _clean_destination(destination),
            "location": None,
            "sections": {},
            "note": "Places API key not configured.",
        }

    city = _clean_destination(destination)
    try:
        center_candidates = _places_text_search(api_key, f"{city} city center", max_results=1)
        location = None
        if center_candidates:
            loc = center_candidates[0].get("location", {})
            if isinstance(loc, dict):
                lat = loc.get("latitude")
                lng = loc.get("longitude")
                if isinstance(lat, (float, int)) and isinstance(lng, (float, int)):
                    location = {"latitude": float(lat), "longitude": float(lng)}

        section_queries = {
            "Top attractions": f"top attractions in {city}",
            "Food picks": f"best local restaurants in {city}",
            "Neighborhoods": f"best neighborhoods to visit in {city}",
        }
        sections: dict[str, list[str]] = {}
        for section_name, query in section_queries.items():
            try:
                results = _places_text_search(api_key, query, max_results=3)
                sections[section_name] = [_format_place_line(p) for p in results[:3]]
            except Exception:
                sections[section_name] = []

        return {"city": city, "location": location, "sections": sections, "note": ""}
    except Exception as e:
        return {"city": city, "location": None, "sections": {}, "note": f"Places lookup failed: {e}"}


def _weather_days_lookup(
    api_key: str,
    latitude: float,
    longitude: float,
    days: int,
) -> dict:
    params = {
        "key": api_key,
        "location.latitude": latitude,
        "location.longitude": longitude,
        "days": days,
    }
    with httpx.Client(timeout=12.0) as client:
        response = client.get("https://weather.googleapis.com/v1/forecast/days:lookup", params=params)
        response.raise_for_status()
        return response.json()


def _fetch_weather_snapshot(
    location: dict[str, float] | None,
    departure_date: str,
    return_date: str,
) -> dict[str, Any]:
    """Fetch short-range forecast lines for trip dates when available."""
    api_key = settings.google_places_api_key
    if not api_key:
        return {"lines": [], "note": "Weather API key not configured."}
    if not location:
        return {"lines": [], "note": "Weather lookup unavailable (destination coordinates missing)."}

    dep = _parse_date(departure_date)
    ret = _parse_date(return_date) if return_date else dep
    if dep is None:
        return {"lines": [], "note": "Weather lookup unavailable (invalid departure date)."}
    if ret is None or ret < dep:
        ret = dep

    trip_days = max((ret - dep).days + 1, 1)
    forecast_days_to_fetch = max(3, min(trip_days, 10))

    try:
        weather = _weather_days_lookup(
            api_key=api_key,
            latitude=location["latitude"],
            longitude=location["longitude"],
            days=forecast_days_to_fetch,
        )
        forecast_days = weather.get("forecastDays", []) or []
        by_date: dict[str, dict] = {}
        for item in forecast_days:
            d = item.get("displayDate", {})
            if not isinstance(d, dict):
                continue
            key = f"{d.get('year', 0):04d}-{d.get('month', 0):02d}-{d.get('day', 0):02d}"
            by_date[key] = item

        lines: list[str] = []
        cursor = dep
        while cursor <= ret:
            key = cursor.strftime("%Y-%m-%d")
            day_forecast = by_date.get(key)
            if day_forecast:
                condition = (
                    day_forecast.get("daytimeForecast", {})
                    .get("weatherCondition", {})
                    .get("description", {})
                    .get("text", "N/A")
                )
                max_temp = day_forecast.get("maxTemperature", {}).get("degrees")
                min_temp = day_forecast.get("minTemperature", {}).get("degrees")
                rain_pct = (
                    day_forecast.get("daytimeForecast", {})
                    .get("precipitation", {})
                    .get("probability", {})
                    .get("percent")
                )

                temp_text = "temp N/A"
                if isinstance(min_temp, (int, float)) and isinstance(max_temp, (int, float)):
                    temp_text = f"{min_temp:.0f}-{max_temp:.0f}C"
                rain_text = f", rain {rain_pct}%" if isinstance(rain_pct, int) else ""
                lines.append(f"- {cursor.strftime('%b %d')}: {condition}, {temp_text}{rain_text}")
            cursor += timedelta(days=1)

        if lines:
            return {"lines": lines, "note": ""}
        return {
            "lines": [],
            "note": (
                "Short-range weather forecast for your exact travel dates is not available yet. "
                "Recheck closer to departure."
            ),
        }
    except Exception as e:
        return {"lines": [], "note": f"Weather lookup failed: {e}"}


def _build_day_by_day_plan(
    city: str,
    days: int,
    highlights: dict[str, list[str]],
) -> list[str]:
    if days <= 1:
        return [
            f"- Day 1: Arrive in {city}, keep plans flexible, and focus on a smooth transfer/check-in.",
        ]

    attraction_names = []
    for line in highlights.get("Top attractions", []):
        attraction_names.append(line.split(" - ")[0].replace("- ", "").strip())

    neighborhood_names = []
    for line in highlights.get("Neighborhoods", []):
        neighborhood_names.append(line.split(" - ")[0].replace("- ", "").strip())

    food_names = []
    for line in highlights.get("Food picks", []):
        food_names.append(line.split(" - ")[0].replace("- ", "").strip())

    plan = [f"- Day 1: Arrive in {city}, hotel check-in, and a light evening walk."]
    for day in range(2, days):
        idx = day - 2
        attraction = attraction_names[idx % len(attraction_names)] if attraction_names else "a top attraction"
        neighborhood = neighborhood_names[idx % len(neighborhood_names)] if neighborhood_names else "a lively district"
        food = food_names[idx % len(food_names)] if food_names else "a well-rated local restaurant"
        plan.append(
            f"- Day {day}: Morning at {attraction}; afternoon in {neighborhood}; dinner at {food}."
        )
    plan.append(f"- Day {days}: Checkout, transfer to airport, and return flight.")
    return plan


@tool
def create_trip_document(
    destination: Annotated[str, Field(description="Trip destination city/country")],
    origin: Annotated[str, Field(description="Trip origin city/country")],
    departure_date: Annotated[str, Field(description="Departure date string (YYYY-MM-DD)")],
    adults: Annotated[int, Field(description="Number of travelers")],
    flights: Annotated[str, Field(description="JSON string of flight options from Amadeus")],
    config: RunnableConfig,
    return_date: Annotated[str, Field(description="Return date string (leave empty for one-way trips)")] = "",
    preferences: Annotated[str, Field(description="User's travel preferences")] = "",
) -> dict:
    """Create a Google Docs trip itinerary document with recommendations."""
    try:
        conf = config.get("configurable", {}) if config else {}
        token = conf.get("google_token", {})
        if not token:
            return {"error": "Google authentication required. Please connect your Google account in the sidebar."}

        docs = _get_docs_service(token)
        drive = _get_drive_service(token)

        dep_dt = _parse_date(departure_date)
        ret_dt = _parse_date(return_date) if return_date else dep_dt
        if dep_dt and ret_dt and ret_dt < dep_dt:
            ret_dt = dep_dt
        trip_days = ((ret_dt - dep_dt).days + 1) if dep_dt and ret_dt else 1
        trip_days = max(trip_days, 1)

        title = f"NaviGO Itinerary: {origin} -> {destination} ({departure_date})"
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        flight_list = _extract_flight_list(flights)[:5]
        flight_option_lines: list[str] = []
        for i, flight in enumerate(flight_list, 1):
            flight_option_lines.extend(_render_flight_option(i, flight))

        ranking_lines = _rank_flights(flight_list, preferences)

        destination_context = _fetch_destination_highlights(destination)
        weather_context = _fetch_weather_snapshot(
            location=destination_context.get("location"),
            departure_date=departure_date,
            return_date=return_date or departure_date,
        )

        day_plan_lines = _build_day_by_day_plan(
            city=destination_context.get("city") or _clean_destination(destination),
            days=trip_days,
            highlights=destination_context.get("sections", {}),
        )

        body_lines = [
            "TRIP ITINERARY",
            "Generated by NaviGO AI Travel Agent",
            "",
            "TRIP DETAILS",
            f"- Origin: {origin}",
            f"- Destination: {destination}",
            f"- Departure: {_pretty_date(departure_date)}",
            f"- Return: {_pretty_date(return_date) if return_date else 'One-way'}",
            f"- Travelers: {adults} adult(s)",
            f"- Preferences: {preferences or 'None specified'}",
            "",
            "FLIGHT OPTIONS",
        ]
        if flight_option_lines:
            body_lines.extend(flight_option_lines)
        else:
            body_lines.append("- No flight data available.")

        body_lines.extend(["", "BOOKING RECOMMENDATION"])
        body_lines.extend([f"- {line}" for line in ranking_lines])

        body_lines.extend(["", "DESTINATION HIGHLIGHTS"])
        sections = destination_context.get("sections", {})
        if sections:
            for section_name in ["Top attractions", "Food picks", "Neighborhoods"]:
                entries = sections.get(section_name, [])
                if not entries:
                    continue
                body_lines.append(f"{section_name}:")
                body_lines.extend(entries)
        else:
            body_lines.append("- No place recommendations available.")
        if destination_context.get("note"):
            body_lines.append(f"- Note: {destination_context['note']}")

        body_lines.extend(["", "WEATHER SNAPSHOT"])
        if weather_context.get("lines"):
            body_lines.extend(weather_context["lines"])
        else:
            body_lines.append(f"- {weather_context.get('note', 'Weather data unavailable.')}")

        body_lines.extend(["", "SUGGESTED DAY-BY-DAY PLAN"])
        body_lines.extend(day_plan_lines)

        body_lines.extend(
            [
                "",
                "TRAVEL CHECKLIST",
                "- Confirm passport/ID validity and visa requirements.",
                "- Book airport transfers.",
                "- Save accommodation and flight confirmations offline.",
                "- Add emergency contacts and travel insurance details.",
            ]
        )

        body_text = "\n".join(body_lines) + "\n"

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

        drive.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return {"success": True, "doc_url": doc_url, "doc_id": doc_id, "title": title}

    except Exception as e:
        return {"error": f"Failed to create document: {str(e)}"}
