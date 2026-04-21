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
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_ft: float = 0.0
    groundspeed_kts: float = 0.0
    fuel_lbs: float = 0.0
    engine_on: bool = False
    on_ground: bool = True
    parking_brake: bool = False
    vertical_speed_fpm: float = 0.0
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
            lat = self._get(ar, "PLANE_LATITUDE", 0.0)
            lon = self._get(ar, "PLANE_LONGITUDE", 0.0)
            alt = self._get(ar, "PLANE_ALTITUDE", 0.0)
            gs = self._get(ar, "GROUND_VELOCITY", 0.0)
            fuel = self._get(ar, "FUEL_TOTAL_QUANTITY_WEIGHT", 0.0)
            eng = self._get(ar, "ENG_COMBUSTION:1", 0)
            on_gnd = self._get(ar, "SIM_ON_GROUND", 1)
            pk_brake = self._get(ar, "BRAKE_PARKING_POSITION", 0)
            vs = self._get(ar, "VERTICAL_SPEED", 0.0)

            tel = Telemetry(
                latitude=float(lat),
                longitude=float(lon),
                altitude_ft=float(alt),
                groundspeed_kts=float(gs),
                fuel_lbs=float(fuel),
                engine_on=bool(int(eng)),
                on_ground=bool(int(on_gnd)),
                parking_brake=bool(int(pk_brake)),
                vertical_speed_fpm=float(vs) * 60,  # SimConnect returns ft/s
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
