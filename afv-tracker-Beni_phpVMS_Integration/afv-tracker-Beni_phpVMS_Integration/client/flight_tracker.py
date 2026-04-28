"""
AFV Tracker - Flight Phase Tracker
Determines the current flight phase from telemetry and emits phase-change events.
Also manages in-flight metrics: distance flown, elapsed time, fuel used.
"""

import math
import time
import logging
from collections import deque
from enum import Enum
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from simconnect_client import Telemetry

log = logging.getLogger(__name__)


class FlightPhase(Enum):
    PRE_FLIGHT  = "PRE-FLIGHT"
    TAXI_OUT    = "TAXI OUT"
    TAKEOFF     = "TAKEOFF"
    CLIMB       = "CLIMB"
    CRUISE      = "CRUISE"
    DESCENT     = "DESCENT"
    APPROACH    = "APPROACH"
    LANDING     = "LANDING"
    TAXI_IN     = "TAXI IN"
    PARKED      = "PARKED"
    
    @property
    def vms_code(self) -> str:
        """Translates internal phase to phpVMS v7 ACARS codes."""
        mapping = {
            FlightPhase.PRE_FLIGHT: "Brd",
            FlightPhase.TAXI_OUT:   "Txi",
            FlightPhase.TAKEOFF:    "Dep",
            FlightPhase.CLIMB:      "Enr",
            FlightPhase.CRUISE:     "Enr",
            FlightPhase.DESCENT:    "Enr",
            FlightPhase.APPROACH:   "App",
            FlightPhase.LANDING:    "Lnd",
            FlightPhase.TAXI_IN:    "Lnd",
            FlightPhase.PARKED:     "Pkd",
        }
        return mapping.get(self, "Enr")


# ── Thresholds ─────────────────────────────────────────────────────────────────
TAXI_SPEED_KTS    = 30.0
CRUISE_BAND_FT    = 500.0    # altitude must stay within this band to be "stable"
CRUISE_STABLE_SEC = 60.0     # seconds of altitude stability before entering CRUISE
APPROACH_ALT_FT   = 10_000.0
APPROACH_DIST_NM  = 50.0

# VS thresholds (applied to the SMOOTHED vertical speed)
CLIMB_VS_FPM      =  300.0   # above this → CLIMB
DESCENT_VS_FPM    = -300.0   # below this → DESCENT
CRUISE_EXIT_FPM   = -500.0   # below this while in CRUISE → leave cruise

VS_SMOOTH_SAMPLES = 4        # rolling-average window for vertical speed


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    R = 3440.065
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


class FlightTracker(QObject):
    """
    Stateful flight phase detector.
    Feed it Telemetry objects via update(); it emits signals on phase changes.

    Signals
    -------
    phase_changed(FlightPhase)
    approach_reached(float)      — distance_nm to destination when APPROACH entered
    flight_complete(dict)        — fired when PARKED detected after landing
    """

    phase_changed    = pyqtSignal(object)
    approach_reached = pyqtSignal(float)
    flight_complete  = pyqtSignal(dict)

    def __init__(self, dest_lat: float = 0.0, dest_lon: float = 0.0, parent=None):
        super().__init__(parent)
        self.dest_lat = dest_lat
        self.dest_lon = dest_lon

        self.phase: FlightPhase = FlightPhase.PRE_FLIGHT
        self._cruise_stable_since: Optional[float] = None
        self._cruise_ref_alt: float = 0.0

        # Rolling VS smoother — filters SimConnect noise spikes
        self._vs_history: deque = deque(maxlen=VS_SMOOTH_SAMPLES)

        # Metrics — clock stays None until we receive real telemetry data.
        # This prevents the clock running while SimConnect is connected but
        # the sim world hasn't loaded yet (all-zero values).
        self._start_time: Optional[float] = None
        self._departure_time: Optional[float] = None
        self._arrival_time: Optional[float] = None
        self._sim_data_valid: bool = False   # set True on first real telemetry
        self._fuel_at_departure: float = 0.0
        self._fuel_at_arrival: float = 0.0
        self._distance_flown_nm: float = 0.0
        self._last_lat: Optional[float] = None
        self._last_lon: Optional[float] = None
        self._touchdown_fpm: Optional[float] = None

        self._prev: Optional[Telemetry] = None
        self._landed: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_destination(self, lat: float, lon: float):
        self.dest_lat = lat
        self.dest_lon = lon

    def update(self, tel: Telemetry) -> FlightPhase:
        # Wait for the sim world to actually load before doing anything.
        # SimConnect delivers all-zero telemetry for several seconds after
        # connection while MSFS is still on the menu screen.
        if not self._sim_data_valid:
            if tel.altitude_ft > 50 or tel.fuel_lbs > 100 or tel.groundspeed_kts > 0:
                self._sim_data_valid = True
                log.info("Valid telemetry received — tracker active.")
                # Mid-flight start: seed the clock and fuel baseline now so the
                # elapsed timer and flight-log fuel figure are meaningful even
                # when TAXI_OUT was never seen this session.
                if not tel.on_ground and self._departure_time is None:
                    self._departure_time = time.time()
                    self._fuel_at_departure = tel.fuel_lbs
                    log.info(
                        "Mid-flight start — clock started, fuel baseline %.0f lbs",
                        self._fuel_at_departure,
                    )
            else:
                return self.phase   # stay PRE_FLIGHT, nothing to track yet

        # Start the clock the moment the plane moves — don't wait for a specific
        # phase transition, which can be missed if tracking started mid-taxi or
        # if engine_on is ambiguous for the current aircraft.
        if self._departure_time is None and tel.groundspeed_kts > 0.5:
            self._departure_time = time.time()
            self._fuel_at_departure = tel.fuel_lbs
            self._distance_flown_nm = 0.0
            log.info("Movement detected — clock started, fuel %.0f lbs",
                     self._fuel_at_departure)

        new_phase = self._compute_phase(tel)
        if new_phase != self.phase:
            log.info("Phase: %s → %s", self.phase.value, new_phase.value)
            self.phase = new_phase
            self.phase_changed.emit(new_phase)
            self._on_phase_entered(new_phase, tel)

        # Accumulate distance
        if self._last_lat is not None:
            d = haversine_nm(self._last_lat, self._last_lon, tel.latitude, tel.longitude)
            if d < 5:  # sanity cap per poll
                self._distance_flown_nm += d
        self._last_lat = tel.latitude
        self._last_lon = tel.longitude

        # Capture landing rate
        if tel.touchdown_fpm is not None:
            self._touchdown_fpm = tel.touchdown_fpm

        self._prev = tel
        return self.phase

    @property
    def distance_to_dest_nm(self) -> float:
        if self._last_lat is None or (self.dest_lat == 0 and self.dest_lon == 0):
            return float("inf")  # unknown destination — never triggers distance thresholds
        return haversine_nm(self._last_lat, self._last_lon, self.dest_lat, self.dest_lon)

    @property
    def elapsed_seconds(self) -> float:
        if self._departure_time is None:
            return 0.0
        end = self._arrival_time or time.time()
        return end - self._departure_time

    # ------------------------------------------------------------------
    # Phase computation
    # ------------------------------------------------------------------

    def _compute_phase(self, tel: Telemetry) -> FlightPhase:
        alt = tel.altitude_ft

        # Smooth vertical speed — SimConnect can spike thousands of FPM instantly
        self._vs_history.append(tel.vertical_speed_fpm)
        vs = sum(self._vs_history) / len(self._vs_history)

        # ── On ground ──────────────────────────────────────────────────
        if tel.on_ground:
            self._cruise_stable_since = None   # reset stability timer on ground
            if tel.groundspeed_kts >= TAXI_SPEED_KTS:
                return FlightPhase.TAKEOFF
            # Any movement = taxiing — ENG_COMBUSTION is unreliable on many aircraft
            if tel.groundspeed_kts > 1.0:
                return FlightPhase.TAXI_IN if self._landed else FlightPhase.TAXI_OUT
            # Stationary: use engine state to distinguish pre-flight from taxi hold
            if not tel.engine_on:
                if tel.parking_brake and self._landed:
                    return FlightPhase.PARKED
                return FlightPhase.PRE_FLIGHT
            return FlightPhase.TAXI_IN if self._landed else FlightPhase.TAXI_OUT

        # ── Airborne ────────────────────────────────────────────────────

        # Approach: below 10 000 ft and close enough to destination
        if alt < APPROACH_ALT_FT and self.phase in (
            FlightPhase.DESCENT, FlightPhase.APPROACH, FlightPhase.CRUISE
        ):
            dist = self.distance_to_dest_nm
            if dist < APPROACH_DIST_NM or self.phase == FlightPhase.APPROACH:
                return FlightPhase.APPROACH

        # Cruise: stay unless smoothed VS shows a real descent has started
        if self.phase == FlightPhase.CRUISE:
            if vs >= CRUISE_EXIT_FPM:   # -500 fpm — noise won't push past this
                return FlightPhase.CRUISE
            # Real top-of-descent — leave cruise
            self._cruise_stable_since = None
            log.info("Leaving CRUISE: smoothed VS = %.0f fpm", vs)

        # Enter cruise: altitude stable for 60 s while climbing
        elif self.phase == FlightPhase.CLIMB and self._is_altitude_stable(alt):
            return FlightPhase.CRUISE

        # Climb / Descent based on smoothed VS
        if vs > CLIMB_VS_FPM:       # +300 fpm
            return FlightPhase.CLIMB
        if vs < DESCENT_VS_FPM:     # -300 fpm
            if alt < APPROACH_ALT_FT:
                dist = self.distance_to_dest_nm
                if dist < APPROACH_DIST_NM:
                    return FlightPhase.APPROACH
            return FlightPhase.DESCENT

        # VS is in the ±300 fpm grey zone — hold whatever phase we're in
        if self.phase in (FlightPhase.CLIMB, FlightPhase.DESCENT, FlightPhase.CRUISE):
            return self.phase
        if self.phase == FlightPhase.APPROACH and alt < APPROACH_ALT_FT:
            return self.phase  # still below 10 000 ft — stay in approach
        # APPROACH above 10 000 ft (e.g. go-around) — fall through to climb/descent

        return FlightPhase.CLIMB   # default airborne fallback

    def _is_altitude_stable(self, alt: float) -> bool:
        """
        Returns True once the aircraft has held within CRUISE_BAND_FT of its
        reference altitude for CRUISE_STABLE_SEC seconds.
        Timer resets only if altitude drifts more than the band — NOT on VS spikes.
        """
        now = time.time()
        if self._cruise_stable_since is None:
            self._cruise_ref_alt = alt
            self._cruise_stable_since = now
            return False
        if abs(alt - self._cruise_ref_alt) > CRUISE_BAND_FT:
            # Altitude actually moved — restart the timer
            self._cruise_ref_alt = alt
            self._cruise_stable_since = now
            return False
        return now - self._cruise_stable_since >= CRUISE_STABLE_SEC

    # ------------------------------------------------------------------
    # Phase entry actions
    # ------------------------------------------------------------------

    def _on_phase_entered(self, phase: FlightPhase, tel: Telemetry):
        if phase == FlightPhase.TAXI_OUT:
            # Clock and fuel baseline already set by the movement detector in
            # update(). Only reset here if we somehow reach TAXI_OUT before
            # any movement was detected (shouldn't normally happen).
            if self._departure_time is None:
                self._departure_time = time.time()
                self._fuel_at_departure = tel.fuel_lbs
                self._distance_flown_nm = 0.0
                log.info("Taxi-out. Clock started. Fuel: %.0f lbs", self._fuel_at_departure)

        if phase == FlightPhase.APPROACH:
            dist = self.distance_to_dest_nm
            self.approach_reached.emit(dist)
            log.info("Approach phase — %.1f nm to destination", dist)

        elif phase == FlightPhase.LANDING:
            self._landed = True

        elif phase == FlightPhase.PARKED:
            self._arrival_time = time.time()
            self._fuel_at_arrival = tel.fuel_lbs
            self._emit_flight_complete()

    def _emit_flight_complete(self):
        payload = {
            "departure_time":  self._departure_time,
            "arrival_time":    self._arrival_time,
            "flight_time_sec": self.elapsed_seconds,
            "fuel_used_lbs":   max(0, self._fuel_at_departure - self._fuel_at_arrival),
            "distance_flown_nm": self._distance_flown_nm,
            "landing_rate_fpm":  self._touchdown_fpm,
        }
        log.info("Flight complete: %s", payload)
        self.flight_complete.emit(payload)
