"""
AFV Tracker - Gate Manager (Client-side)
Requests gate assignments from the backend API and caches the result.
Also maps aircraft ICAO type codes to gate size categories.
"""

import logging
from typing import Optional
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


# Aircraft type → gate size mapping
AIRCRAFT_GATE_SIZE: dict[str, str] = {
    # Small (turboprops / regional)
    "AT76": "S", "AT75": "S", "AT72": "S",
    "DH8D": "S", "DH8C": "S", "DH8B": "S", "DH8A": "S",
    "E145": "S", "E135": "S", "E170": "S",
    "SF34": "S", "BE20": "S", "C208": "S",
    # Medium (narrowbody)
    "B737": "M", "B738": "M", "B739": "M", "B73G": "M",
    "B733": "M", "B734": "M", "B735": "M",
    "A318": "M", "A319": "M", "A320": "M", "A321": "M",
    "E190": "M", "E195": "M", "E75L": "M", "E75S": "M",
    "CRJ9": "M", "CRJ7": "M",
    # Large (widebody)
    "B787": "L", "B788": "L", "B789": "L", "B78X": "L",
    "B763": "L", "B764": "L", "B762": "L",
    "A330": "L", "A332": "L", "A333": "L",
    "A350": "L", "A359": "L", "A35K": "L",
    "B77W": "L", "B773": "L", "B772": "L",
    # Heavy / Super
    "B744": "H", "B74S": "H", "B74D": "H",
    "A388": "H", "A380": "H",
    "A124": "H", "C17":  "H",
}


def get_gate_size(aircraft_icao: str) -> str:
    """Return gate size (S/M/L/H) for an aircraft type. Defaults to M."""
    return AIRCRAFT_GATE_SIZE.get(aircraft_icao.upper(), "M")


@dataclass
class GateAssignment:
    gate_number: str
    terminal: str
    gate_size: str
    airport_icao: str
    fallback: bool = False      # True if no size-matched gate found


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
            gate_size=data.get("gate_size", "M"),
            airport_icao=airport_icao,
            fallback=data.get("fallback", False),
        )
        self._assignment = assignment
        log.info("Gate assigned: %s / Terminal %s",
                 assignment.gate_number, assignment.terminal)
        return assignment

    def fetch_gate_board(self, airport_icao: str,
                         timeout: int = 5) -> list[dict]:
        """
        Fetch all gates at an airport for the gate board display.
        Returns a list of gate dicts or empty list on failure.
        """
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
        """
        Tell the server to release this gate reservation.
        Returns True on success, False on any failure (safe to ignore).
        """
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
