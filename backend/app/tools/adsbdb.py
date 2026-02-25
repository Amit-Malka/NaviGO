"""ADSBDB Tool — free, no API key required.
Docs: https://www.adsbdb.com/
"""
import httpx
from langchain_core.tools import tool

ADSBDB_BASE = "https://api.adsbdb.com/v0"
TIMEOUT = 10.0


@tool
async def search_aircraft_by_callsign(callsign: str) -> dict:
    """Look up live/recent flight information by airline callsign (e.g. 'EL316', 'LY316').
    Returns aircraft type, route, and operator information.
    Use this to enrich flight search results with aircraft details."""
    callsign = callsign.upper().strip()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(f"{ADSBDB_BASE}/callsign/{callsign}")
            if resp.status_code == 200:
                data = resp.json()
                flightroute = data.get("response", {}).get("flightroute", {})
                if not flightroute:
                    return {"error": f"No route data found for callsign {callsign}"}
                aircraft = flightroute.get("aircraft", {})
                return {
                    "callsign": callsign,
                    "airline": flightroute.get("airline", {}).get("name", "Unknown"),
                    "origin": flightroute.get("origin", {}).get("iata_code", "?"),
                    "destination": flightroute.get("destination", {}).get("iata_code", "?"),
                    "aircraft_type": aircraft.get("type", "Unknown"),
                    "aircraft_manufacturer": aircraft.get("manufacturer", "Unknown"),
                    "registration": aircraft.get("registration", "N/A"),
                }
            elif resp.status_code == 404:
                return {"error": f"Callsign {callsign} not found in ADSBDB"}
            else:
                return {"error": f"ADSBDB returned status {resp.status_code}"}
        except httpx.TimeoutException:
            return {"error": "ADSBDB request timed out"}
        except Exception as e:
            return {"error": f"ADSBDB error: {str(e)}"}


@tool
async def search_aircraft_by_registration(registration: str) -> dict:
    """Look up aircraft details by registration (tail number), e.g. '4X-EHA'.
    Returns aircraft type, operator, and manufacturer info."""
    registration = registration.upper().strip()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(f"{ADSBDB_BASE}/aircraft/{registration}")
            if resp.status_code == 200:
                data = resp.json()
                aircraft = data.get("response", {}).get("aircraft", {})
                if not aircraft:
                    return {"error": f"No aircraft found for registration {registration}"}
                return {
                    "registration": registration,
                    "type": aircraft.get("type", "Unknown"),
                    "manufacturer": aircraft.get("manufacturer", "Unknown"),
                    "operator": aircraft.get("registered_owner", "Unknown"),
                    "country": aircraft.get("registered_owner_country_name", "Unknown"),
                }
            elif resp.status_code == 404:
                return {"error": f"Registration {registration} not found"}
            else:
                return {"error": f"ADSBDB returned status {resp.status_code}"}
        except httpx.TimeoutException:
            return {"error": "ADSBDB request timed out"}
        except Exception as e:
            return {"error": f"ADSBDB error: {str(e)}"}
