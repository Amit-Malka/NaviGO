"""Amadeus Flights Tool — uses official Amadeus Python SDK.
Uses test environment by default (free, no billing).
"""
from amadeus import Client, ResponseError
from langchain_core.tools import tool
from app.config import settings

_client: Client | None = None


def get_amadeus_client() -> Client:
    global _client
    if _client is None:
        _client = Client(
            client_id=settings.amadeus_client_id,
            client_secret=settings.amadeus_client_secret,
            hostname=settings.amadeus_hostname,
        )
    return _client


@tool
def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    return_date: str | None = None,
    max_results: int = 3,
) -> dict:
    """Search for available flights between two airports.

    Args:
        origin: IATA airport code for departure (e.g. 'TLV', 'JFK', 'LHR')
        destination: IATA airport code for arrival (e.g. 'BCN', 'CDG')
        departure_date: Date in YYYY-MM-DD format
        adults: Number of adult passengers (default 1)
        return_date: Return date in YYYY-MM-DD format (omit for one-way)
        max_results: Max number of offers to return (default 3)

    Returns a list of flight offers with price, airline, duration, and stops.
    """
    client = get_amadeus_client()
    try:
        params = {
            "originLocationCode": origin.upper().strip(),
            "destinationLocationCode": destination.upper().strip(),
            "departureDate": departure_date,
            "adults": adults,
            "max": max_results,
            "currencyCode": "USD",
        }
        if return_date:
            params["returnDate"] = return_date

        response = client.shopping.flight_offers_search.get(**params)
        offers = response.data

        if not offers:
            return {
                "error": "No flights found",
                "suggestion": "Try adjacent dates or check if IATA codes are correct",
                "searched": params,
            }

        results = []
        for offer in offers:
            itineraries = offer.get("itineraries", [])
            price = offer.get("price", {})
            validating_airline = offer.get("validatingAirlineCodes", ["?"])[0]

            legs = []
            for itin in itineraries:
                segments = itin.get("segments", [])
                duration = itin.get("duration", "PT?H").replace("PT", "").lower()
                stops = len(segments) - 1
                first_seg = segments[0] if segments else {}
                last_seg = segments[-1] if segments else {}
                legs.append({
                    "departure": first_seg.get("departure", {}).get("at", "?"),
                    "arrival": last_seg.get("arrival", {}).get("at", "?"),
                    "duration": duration,
                    "stops": stops,
                    "airline": validating_airline,
                })

            results.append({
                "price": f"${price.get('grandTotal', '?')} {price.get('currency', 'USD')}",
                "airline_code": validating_airline,
                "legs": legs,
            })

        return {"flights": results, "count": len(results)}

    except ResponseError as e:
        error_msg = str(e)
        # Detect IATA code errors for self-correction
        if "INVALID FORMAT" in error_msg or "locationCode" in error_msg.lower():
            return {
                "error": "Invalid IATA airport code",
                "correction_hint": f"Look up the correct IATA code for '{origin}' or '{destination}' using search_airport_by_city",
                "raw_error": error_msg,
            }
        return {"error": f"Amadeus API error: {error_msg}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


@tool
def search_airport_by_city(city_name: str) -> dict:
    """Search for airport IATA codes by city name.
    Use this when a user provides a city name instead of an IATA code,
    or when search_flights returns an 'Invalid IATA code' error.

    Args:
        city_name: Name of the city (e.g. 'Barcelona', 'Tel Aviv', 'New York')
    """
    client = get_amadeus_client()
    try:
        response = client.reference_data.locations.get(
            keyword=city_name,
            subType="AIRPORT,CITY",
        )
        locations = response.data[:5]  # top 5 matches
        if not locations:
            return {"error": f"No airports found for '{city_name}'"}

        results = []
        for loc in locations:
            results.append({
                "iata_code": loc.get("iataCode", "?"),
                "name": loc.get("name", "?"),
                "city": loc.get("address", {}).get("cityName", "?"),
                "country": loc.get("address", {}).get("countryName", "?"),
            })
        return {"airports": results}

    except ResponseError as e:
        return {"error": f"Amadeus error: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}
