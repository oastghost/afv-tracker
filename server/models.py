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
    vatsim_cid:      str
    flight_number:   Optional[str] = None
    phase:           str
    timestamp:       Optional[float] = None
    # Position
    latitude:        float
    longitude:       float
    altitude_ft:     float
    # Attitude
    heading_mag:     Optional[float] = None
    pitch_deg:       Optional[float] = None
    bank_deg:        Optional[float] = None
    # Speed
    groundspeed_kts: float
    ias_kts:         Optional[float] = None
    tas_kts:         Optional[float] = None
    mach:            Optional[float] = None
    vertical_speed_fpm: Optional[float] = None
    # Engines
    eng1_on:         Optional[float] = None
    eng2_on:         Optional[float] = None
    eng3_on:         Optional[float] = None
    eng4_on:         Optional[float] = None
    eng1_n1:         Optional[float] = None
    eng2_n1:         Optional[float] = None
    eng3_n1:         Optional[float] = None
    eng4_n1:         Optional[float] = None
    # Fuel
    fuel_lbs:        float
    fuel_qty_gal:    Optional[float] = None
    # Systems
    autopilot_on:    Optional[float] = None
    autopilot_alt_ft: Optional[float] = None
    autopilot_hdg:   Optional[float] = None
    flaps_pct:       Optional[float] = None
    gear_down:       Optional[float] = None
    transponder:     Optional[int]   = None
    parking_brake:   Optional[float] = None
    # Lights
    lights_strobe:   Optional[float] = None
    lights_landing:  Optional[float] = None
    # Ambient
    wind_speed_kts:  Optional[float] = None
    wind_dir_deg:    Optional[float] = None
    oat_celsius:     Optional[float] = None
    qnh_mb:          Optional[float] = None


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
