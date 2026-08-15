"""
AFV Tracker - SimBrief Integration
Fetches and parses the latest OFP from the SimBrief API.
"""

import requests
from dataclasses import dataclass, field
from typing import Optional


SIMBRIEF_API_URL = "https://www.simbrief.com/api/xml.fetcher.php"


@dataclass
class FuelFigures:
    planned_lbs: float
    alternate_lbs: float
    reserve_lbs: float
    taxi_lbs: float
    total_lbs: float


@dataclass
class OFP:
    # Identification
    pilot_id: str
    airline: str
    flight_number: str
    callsign: str

    # Route
    origin_icao: str
    origin_name: str
    destination_icao: str
    destination_name: str
    alternate_icao: str
    route: str

    # Aircraft
    aircraft_icao: str
    aircraft_name: str
    registration: str

    # Performance
    cruise_altitude: int          # feet
    est_flight_time_min: int      # minutes
    distance_nm: int

    # Fuel
    fuel: FuelFigures

    # Times (UTC strings, e.g. "0130" = 01:30Z)
    atd_utc: str                  # actual time of departure (scheduled)
    eta_utc: str

    # Weights (lbs)
    zfw_lbs: float
    tow_lbs: float

    # Raw payload for debugging
    raw: dict = field(default_factory=dict, repr=False)


class SimBriefError(Exception):
    pass


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def fetch_ofp(pilot_id: str, timeout: int = 15) -> OFP:
    """
    Fetch the latest OFP for a SimBrief pilot.
    Raises SimBriefError on any failure.
    """
    if not pilot_id or not pilot_id.strip():
        raise SimBriefError("Pilot ID cannot be empty.")

    pid = pilot_id.strip()
    # SimBrief accepts userid= for numeric IDs, username= for text usernames
    if pid.isdigit():
        params = {"userid": pid, "json": "1"}
    else:
        params = {"username": pid, "json": "1"}

    try:
        resp = requests.get(SIMBRIEF_API_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise SimBriefError("SimBrief API timed out. Check your internet connection.")
    except requests.exceptions.ConnectionError:
        raise SimBriefError("Cannot reach SimBrief. Check your internet connection.")
    except requests.exceptions.HTTPError as e:
        raise SimBriefError(f"SimBrief API returned an error: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise SimBriefError("SimBrief returned an invalid response (not JSON).")

    # Check for API-level error
    if "fetch" in data and data["fetch"].get("status") == "Error":
        msg = data["fetch"].get("message", "Unknown SimBrief error")
        raise SimBriefError(f"SimBrief API: {msg}")

    if "general" not in data:
        raise SimBriefError(
            "Unexpected SimBrief response format. "
            "Check your Pilot ID and try again."
        )

    try:
        return _parse_ofp(pid, data)
    except KeyError as e:
        raise SimBriefError(f"Failed to parse SimBrief OFP (missing field: {e}).")


def _parse_ofp(pilot_id: str, data: dict) -> OFP:
    general = data.get("general", {})
    origin = data.get("origin", {})
    destination = data.get("destination", {})
    aircraft = data.get("aircraft", {})
    fuel = data.get("fuel", {})
    times = data.get("times", {})
    weights = data.get("weights", {})
    alternate = data.get("alternate", {})

    # Fuel figures (all in lbs)
    fuel_figures = FuelFigures(
        planned_lbs=_safe_float(fuel.get("plan_ramp")),
        alternate_lbs=_safe_float(fuel.get("alternate_burn")),
        reserve_lbs=_safe_float(fuel.get("reserve")),
        taxi_lbs=_safe_float(fuel.get("taxi")),
        total_lbs=_safe_float(fuel.get("plan_ramp")),
    )

    # Flight time: SimBrief gives it in minutes as "est_time_enroute"
    est_time_raw = _safe_int(times.get("est_time_enroute", 0))
    # Sometimes it's in seconds
    if est_time_raw > 3600:
        est_time_min = est_time_raw // 60
    else:
        est_time_min = est_time_raw

    # Departure/arrival UTC
    sched_out = times.get("sched_out", "")
    sched_in = times.get("sched_in", "")

    # Format HH:MM from epoch seconds if needed
    atd_str = _format_utc_time(sched_out)
    eta_str = _format_utc_time(sched_in)

    # 1. Get the values safely
    icao_air = general.get("icao_airline")
    f_num = general.get("flight_number", "")

    # 2. Check if SimBrief sent a dictionary instead of a string
    if not icao_air or isinstance(icao_air, dict):
        icao_air = ""
    
    if not f_num or isinstance(f_num, dict):
        f_num = ""

    # 3. Combine them (f-string will handle the empty icao_air perfectly)
    full_callsign = f"{icao_air}{f_num}"

    return OFP(
        pilot_id=pilot_id,
        airline=general.get("airline", "AFV"),
        flight_number=str(f_num), # Force to string for the UI
        callsign=full_callsign,
        origin_icao=origin.get("icao_code", ""),
        origin_name=origin.get("name", ""),
        destination_icao=destination.get("icao_code", ""),
        destination_name=destination.get("name", ""),
        alternate_icao=alternate.get("icao_code", ""),
        route=general.get("route", ""),
        aircraft_icao=aircraft.get("icao_code", ""),
        aircraft_name=aircraft.get("name", ""),
        registration=aircraft.get("reg", ""),
        cruise_altitude=_safe_int(general.get("initial_altitude", 0)),
        est_flight_time_min=est_time_min,
        distance_nm=_safe_int(general.get("air_distance", 0)),
        fuel=fuel_figures,
        atd_utc=atd_str,
        eta_utc=eta_str,
        zfw_lbs=_safe_float(weights.get("est_zfw")),
        tow_lbs=_safe_float(weights.get("est_tow")),
        raw=data,
    )


def _format_utc_time(value) -> str:
    """Convert epoch seconds to HH:MMz. Safely handles dicts/None."""
    if not value or isinstance(value, dict): # Add dict check here
        return "----"
    try:
        epoch = int(value)
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return dt.strftime("%H:%Mz")
    except (ValueError, OSError, TypeError): # Add TypeError here
        return str(value)   
