"""
AFV Tracker - SimConnect Client
Polls MSFS via SimConnect every N seconds and emits telemetry data.
Runs in a background QThread so it never blocks the GUI.
"""

import time
import math
import logging
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)

# Try to import SimConnect — graceful fallback if MSFS not installed
try:
    from SimConnect import SimConnect, AircraftRequests
    SIMCONNECT_AVAILABLE = True
except ImportError:
    SIMCONNECT_AVAILABLE = False
    log.warning("SimConnect library not found. Simulator connection will be unavailable.")


@dataclass
class Telemetry:
    # Position
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_ft: float = 0.0
    # Attitude
    heading_mag: float = 0.0
    heading_true: float = 0.0
    pitch_deg: float = 0.0
    bank_deg: float = 0.0
    # Speed
    groundspeed_kts: float = 0.0
    ias_kts: float = 0.0
    tas_kts: float = 0.0
    mach: float = 0.0
    vertical_speed_fpm: float = 0.0
    # Engines (engine_on = eng1 combustion, kept for phase detection)
    engine_on: bool = False
    eng2_on: bool = False
    eng3_on: bool = False
    eng4_on: bool = False
    eng1_n1: float = 0.0
    eng2_n1: float = 0.0
    eng3_n1: float = 0.0
    eng4_n1: float = 0.0
    # Fuel
    fuel_lbs: float = 0.0
    fuel_qty_gal: float = 0.0
    # Systems
    on_ground: bool = True
    parking_brake: bool = False
    autopilot_on: bool = False
    autopilot_alt_ft: float = 0.0
    autopilot_hdg: float = 0.0
    flaps_pct: float = 0.0
    gear_down: bool = True
    transponder: int = 2000
    # Lights
    lights_strobe: bool = False
    lights_landing: bool = False
    # Ambient / weather
    wind_speed_kts: float = 0.0
    wind_dir_deg: float = 0.0
    oat_celsius: float = 0.0
    qnh_mb: float = 1013.0
    # Set at touchdown
    touchdown_fpm: Optional[float] = None
    timestamp: float = field(default_factory=time.time)


def detect_sim_version() -> str:
    """
    Detect whether MSFS 2020 or 2024 is the running instance by inspecting
    the FlightSimulator.exe executable path via wmic.
    Returns 'MSFS 2024', 'MSFS 2020', or 'MSFS' if undetermined.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["wmic", "process", "where", "name='FlightSimulator.exe'",
             "get", "ExecutablePath"],
            capture_output=True, text=True, timeout=5,
        )
        path = result.stdout.lower()
        if "2024" in path or "fs24" in path:
            return "MSFS 2024"
        if "flightsimulator" in path:
            return "MSFS 2020"
    except Exception:
        pass
    return "MSFS"


class SimConnectWorker(QThread):
    """
    Background thread that connects to MSFS via SimConnect and polls telemetry.
    Works with both MSFS 2020 and MSFS 2024 — auto-connects to whichever is running.

    Signals
    -------
    telemetry_update(Telemetry)  — emitted every poll cycle
    connected(str)               — emitted when SimConnect link is established; carries sim version string
    disconnected()               — emitted when link drops
    error(str)                   — emitted on unrecoverable error
    """

    telemetry_update = pyqtSignal(object)
    connected = pyqtSignal(str)   # sim version string, e.g. "MSFS 2020"
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, poll_interval: int = 5, parent=None):
        super().__init__(parent)
        self.poll_interval = poll_interval
        self._running = False
        self._connected = False

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self):
        self._running = True

        if not SIMCONNECT_AVAILABLE:
            self.error.emit(
                "SimConnect library is not installed.\n"
                "Run: pip install SimConnect"
            )
            return

        while self._running:
            sm = None
            ar = None
            try:
                log.info("Attempting SimConnect connection…")
                sm = SimConnect()
                ar = AircraftRequests(sm, _time=2000)
                self._connected = True
                version = detect_sim_version()
                self.connected.emit(version)
                log.info("SimConnect connected — %s", version)

                prev_on_ground = True
                prev_altitude = 0.0

                while self._running:
                    tel = self._poll(ar, prev_on_ground, prev_altitude)
                    if tel is None:
                        break  # connection dropped
                    self.telemetry_update.emit(tel)
                    prev_on_ground = tel.on_ground
                    prev_altitude = tel.altitude_ft
                    time.sleep(self.poll_interval)

            except Exception as exc:  # noqa: BLE001
                log.warning("SimConnect error: %s", exc)
            finally:
                if sm:
                    try:
                        sm.exit()
                    except Exception:
                        pass
                if self._connected:
                    self._connected = False
                    self.disconnected.emit()

            if self._running:
                log.info("Retrying SimConnect in 10 seconds…")
                time.sleep(10)

    def stop(self):
        self._running = False
        self.wait(3000)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _poll(self, ar: "AircraftRequests", prev_on_ground: bool, prev_alt: float) -> Optional[Telemetry]:
        try:
            # PLANE_HEADING_DEGREES_TRUE is not in the SimConnect Python library's variable
            # list, so we compute it from magnetic heading + magnetic variation (MAGVAR).
            # SimConnect MAGVAR: positive = East, negative = West.
            # True = Magnetic + Variation (East positive).
            _heading_mag = float(self._get(ar, "PLANE_HEADING_DEGREES_MAGNETIC", 0.0))
            _magvar = float(self._get(ar, "MAGVAR", 0.0))
            _heading_true = (_heading_mag + _magvar) % 360.0

            tel = Telemetry(
                # Position
                latitude=float(self._get(ar, "PLANE_LATITUDE", 0.0)),
                longitude=float(self._get(ar, "PLANE_LONGITUDE", 0.0)),
                altitude_ft=float(self._get(ar, "PLANE_ALTITUDE", 0.0)),
                # Attitude
                heading_mag=_heading_mag,
                heading_true=_heading_true,
                pitch_deg=float(self._get(ar, "PLANE_PITCH_DEGREES", 0.0)),
                bank_deg=float(self._get(ar, "PLANE_BANK_DEGREES", 0.0)),
                # Speed
                groundspeed_kts=float(self._get(ar, "GROUND_VELOCITY", 0.0)),
                ias_kts=float(self._get(ar, "AIRSPEED_INDICATED", 0.0)),
                tas_kts=float(self._get(ar, "AIRSPEED_TRUE", 0.0)),
                mach=float(self._get(ar, "AIRSPEED_MACH", 0.0)),
                vertical_speed_fpm=float(self._get(ar, "VERTICAL_SPEED", 0.0)) * 60,
                # Engines
                engine_on=bool(int(self._get(ar, "GENERAL_ENG_COMBUSTION:1", 0))),
                eng2_on=bool(int(self._get(ar, "GENERAL_ENG_COMBUSTION:2", 0))),
                eng3_on=bool(int(self._get(ar, "GENERAL_ENG_COMBUSTION:3", 0))),
                eng4_on=bool(int(self._get(ar, "GENERAL_ENG_COMBUSTION:4", 0))),
                eng1_n1=float(self._get(ar, "TURB_ENG_N1:1", 0.0)),
                eng2_n1=float(self._get(ar, "TURB_ENG_N1:2", 0.0)),
                eng3_n1=float(self._get(ar, "TURB_ENG_N1:3", 0.0)),
                eng4_n1=float(self._get(ar, "TURB_ENG_N1:4", 0.0)),
                # Fuel
                fuel_lbs=float(self._get(ar, "FUEL_TOTAL_QUANTITY_WEIGHT", 0.0)),
                fuel_qty_gal=float(self._get(ar, "FUEL_TOTAL_QUANTITY", 0.0)),
                # Systems
                on_ground=bool(int(self._get(ar, "SIM_ON_GROUND", 1))),
                parking_brake=bool(int(self._get(ar, "BRAKE_PARKING_POSITION", 0))),
                autopilot_on=bool(int(self._get(ar, "AUTOPILOT_MASTER", 0))),
                autopilot_alt_ft=float(self._get(ar, "AUTOPILOT_ALTITUDE_LOCK_VAR", 0.0)),
                autopilot_hdg=float(self._get(ar, "AUTOPILOT_HEADING_LOCK_DIR", 0.0)),
                flaps_pct=float(self._get(ar, "FLAPS_HANDLE_PERCENT", 0.0)),
                gear_down=bool(int(self._get(ar, "GEAR_HANDLE_POSITION", 1))),
                transponder=int(self._get(ar, "TRANSPONDER_CODE:1", 2000)),
                # Lights
                lights_strobe=bool(int(self._get(ar, "LIGHT_STROBE", 0))),
                lights_landing=bool(int(self._get(ar, "LIGHT_LANDING", 0))),
                # Ambient
                wind_speed_kts=float(self._get(ar, "AMBIENT_WIND_VELOCITY", 0.0)),
                wind_dir_deg=float(self._get(ar, "AMBIENT_WIND_DIRECTION", 0.0)),
                oat_celsius=float(self._get(ar, "AMBIENT_TEMPERATURE", 0.0)),
                qnh_mb=float(self._get(ar, "AMBIENT_PRESSURE", 1013.0)),
                timestamp=time.time(),
            )

            # Capture landing rate at touchdown
            if prev_on_ground is False and tel.on_ground is True:
                tel.touchdown_fpm = abs(tel.vertical_speed_fpm)
                log.info("Touchdown! Rate: %.0f fpm", tel.touchdown_fpm)

            return tel

        except Exception as exc:
            log.warning("Poll error — assuming disconnected: %s", exc)
            return None

    @staticmethod
    def _get(ar: "AircraftRequests", var: str, default):
        try:
            val = ar.get(var)
            return val if val is not None else default
        except Exception:
            return default
