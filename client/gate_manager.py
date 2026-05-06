"""
AFV Tracker - Gate Manager (Client-side)
Requests gate assignments from the backend API and caches the result.
Maps aircraft ICAO type codes to DB wake-turbulence categories:
  Light | Medium | Heavy | Jumbo
"""

import logging
from typing import Optional
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


# Aircraft type → DB size_category (wake-turbulence category)
AIRCRAFT_GATE_SIZE: dict[str, str] = {
    # Light (turboprops / small piston)
    "AT76": "Light", "AT75": "Light", "AT72": "Light",
    "DH8D": "Light", "DH8C": "Light", "DH8B": "Light", "DH8A": "Light",
    "E145": "Light", "E135": "Light",
    "SF34": "Light", "BE20": "Light", "C208": "Light", "C207": "Light",
    "PC12": "Light", "TBM9": "Light", "BE9L": "Light", "C182": "Light",
    # Medium (narrowbody)
    "B737": "Medium", "B738": "Medium", "B739": "Medium", "B73G": "Medium",
    "B733": "Medium", "B734": "Medium", "B735": "Medium",
    "B752": "Medium", "B753": "Medium",
    "A318": "Medium", "A319": "Medium", "A320": "Medium", "A321": "Medium",
    "E170": "Medium", "E190": "Medium", "E195": "Medium",
    "E75L": "Medium", "E75S": "Medium",
    "CRJ9": "Medium", "CRJ7": "Medium",
    # Heavy (widebody)
    "B787": "Heavy", "B788": "Heavy", "B789": "Heavy", "B78X": "Heavy",
    "B763": "Heavy", "B764": "Heavy", "B762": "Heavy",
    "A330": "Heavy", "A332": "Heavy", "A333": "Heavy", "A339": "Heavy",
    "A350": "Heavy", "A359": "Heavy", "A35K": "Heavy",
    "A342": "Heavy", "A343": "Heavy", "A346": "Heavy",
    "B77W": "Heavy", "B773": "Heavy", "B772": "Heavy",
    "MD11": "Heavy",
    # Jumbo
    "B744": "Jumbo", "B74S": "Jumbo", "B74D": "Jumbo",
    "A388": "Jumbo", "A380": "Jumbo",
    "A124": "Jumbo", "C17":  "Jumbo",
}


def get_gate_size(aircraft_icao: str) -> str:
    """Return the DB size category for an aircraft type. Defaults to Medium."""
    return AIRCRAFT_GATE_SIZE.get(aircraft_icao.upper(), "Medium")


@dataclass
class GateAssignment:
    gate_number: str
    terminal: str
    gate_size: str       # Light | Medium | Heavy | Jumbo
    airport_icao: str
    fallback: bool = False


class GateManager:
    def __init__(self, server_url: str,
                 pilot_id: str = "", pilot_name: str = ""):
        self.server_url = server_url.rstrip("/")
        self.pilot_id   = pilot_id
        self.pilot_name = pilot_name
        self._assignment: Optional[GateAssignment] = None

    @property
    def current_assignment(self) -> Optional[GateAssignment]:
        return self._assignment

    def request_gate(self, airport_icao: str, aircraft_icao: str,
                     aircraft_reg: str = "", timeout: int = 10) -> GateAssignment:
        """
        Ask the backend for a gate.
        aircraft_reg (e.g. "C9-AIA") is written directly to gates.aircraft_reg
        so the virtual occupied column reflects it immediately.
        """
        url = f"{self.server_url}/api/gates/{airport_icao}/assign"
        params = {
            "aircraft_type": aircraft_icao,
            "pilot_id":      self.pilot_id,
            "pilot_name":    self.pilot_name,
            "aircraft_reg":  aircraft_reg,
        }

        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError:
            log.warning("Cannot reach server — using fallback gate assignment.")
            assignment = GateAssignment(
                gate_number="CONTACT GROUND",
                terminal="",
                gate_size=get_gate_size(aircraft_icao),
                airport_icao=airport_icao,
                fallback=True,
            )
            self._assignment = assignment
            return assignment

        assignment = GateAssignment(
            gate_number=data.get("gate_number", "TBD"),
            terminal=data.get("terminal", ""),
            gate_size=data.get("gate_size", "Medium"),
            airport_icao=airport_icao,
            fallback=data.get("fallback", False),
        )
        self._assignment = assignment
        log.info("Gate assigned: %s / Terminal %s",
                 assignment.gate_number, assignment.terminal)
        return assignment

    def fetch_gate_board(self, airport_icao: str,
                         timeout: int = 5) -> list[dict]:
        """Fetch all gates at an airport for the gate board display."""
        url = f"{self.server_url}/api/gates/{airport_icao}"
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.warning("Gate board fetch failed: %s", exc)
            return []

    def release_gate(self, airport_icao: str, gate_name: str,
                     timeout: int = 5) -> bool:
        """Tell the server to release this gate reservation."""
        url = f"{self.server_url}/api/gates/{airport_icao}/{gate_name}/release"
        try:
            resp = requests.post(url, timeout=timeout)
            resp.raise_for_status()
            log.info("Gate %s/%s released.", airport_icao, gate_name)
            self._assignment = None
            return True
        except Exception as exc:
            log.warning("Gate release failed: %s", exc)
            return False

    def clear(self):
        self._assignment = None
