"""
AFV Tracker - Pydantic models for API request/response validation.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ── Pilots ─────────────────────────────────────────────────────────────────────

class PilotRegisterRequest(BaseModel):
    vatsim_cid:  str           = Field(..., min_length=1, max_length=20)
    simbrief_id: Optional[str] = None
    name:        str           = Field(..., min_length=1, max_length=128)
    discord:     Optional[str] = None


class PilotResponse(BaseModel):
    id:           int
    vatsim_cid:   str
    simbrief_id:  Optional[str]
    name:         str
    discord:      Optional[str]
    total_flights: int
    total_hours:   float
    created_at:   datetime


# ── Telemetry ──────────────────────────────────────────────────────────────────

class TelemetryUpdate(BaseModel):
    vatsim_cid:     str
    flight_number:  Optional[str] = None
    latitude:       float
    longitude:      float
    altitude_ft:    float
    groundspeed_kts: float
    fuel_lbs:       float
    phase:          str
    timestamp:      Optional[float] = None


# ── Flights ────────────────────────────────────────────────────────────────────

class FlightCompleteRequest(BaseModel):
    vatsim_cid:       str
    pilot_name:       Optional[str] = None
    callsign:         Optional[str] = None
    flight_number:    Optional[str] = None
    origin:           str
    destination:      str
    aircraft_type:    str
    departure_time:   Optional[float] = None     # epoch seconds
    arrival_time:     Optional[float] = None
    flight_time_sec:  float = 0.0
    fuel_used_lbs:    float = 0.0
    distance_flown_nm: float = 0.0
    landing_rate_fpm: Optional[float] = None


class FlightLogResponse(BaseModel):
    id:               int
    vatsim_cid:       str
    flight_number:    Optional[str]
    origin:           str
    destination:      str
    aircraft_type:    str
    departure_time:   Optional[datetime]
    arrival_time:     Optional[datetime]
    flight_time_min:  float
    fuel_used_lbs:    float
    distance_nm:      float
    landing_rate_fpm: Optional[float]


# ── Gates ──────────────────────────────────────────────────────────────────────

class GateResponse(BaseModel):
    id:           Optional[int]  # None when using the Africana VA database (no integer PK)
    airport_icao: str
    gate_number:  str
    terminal:     str            # mapped from flight_type: National / International / Remote
    gate_size:    str            # S / M / L / H  (mapped from Light/Medium/Heavy/Jumbo)
    is_available: bool


class GateAssignmentResponse(BaseModel):
    airport_icao: str
    gate_number:  str
    terminal:     str
    gate_size:    str
    fallback:     bool = False
    message:      Optional[str] = None
