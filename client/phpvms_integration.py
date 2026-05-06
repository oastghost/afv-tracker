import requests
import logging
import config

log = logging.getLogger(__name__)


class PhpVmsClient:
    def __init__(self):
        self.current_pirep_id = None
        self.base_url = ""
        self.api_key = ""
        self.headers = {}
        self.refresh_credentials()

    def refresh_credentials(self):
        """Reload URL and API key from config."""
        self.base_url = config.get("VA_URL", "https://africanava.ddns.net").rstrip('/')
        self.api_key = config.get("Pilot_Key", "")
        self.headers = {
            'X-API-Key': self.api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        log.info("phpVMS credentials refreshed for %s", self.base_url)

    def test_connection(self):
        """Return True if the API key and base URL are valid."""
        if not self.api_key:
            return False
        try:
            r = requests.get(f"{self.base_url}/api/user", headers=self.headers, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def get_bids(self):
        """Fetch active flight bids for the authenticated pilot."""
        # phpVMS v7 docs: GET /api/user/bids
        url = f"{self.base_url}/api/user/bids"
        try:
            r = requests.get(url, headers=self.headers, timeout=10)
            r.raise_for_status()
            return r.json().get('data', [])
        except Exception as e:
            log.error("Failed to fetch bids: %s", e)
            return []

    def prefile_pirep(self, bid_data, planned_fuel, flight_level, route=""):
        """
        Prefile a PIREP from a phpVMS bid.
        Uses flight_id (not bid_id) so phpVMS links the PIREP to the schedule.

        phpVMS v7 PrefileRequest (app/Http/Requests/Acars/PrefileRequest.php):
          Required: airline_id, aircraft_id, flight_number,
                    dpt_airport_id, arr_airport_id, source_name
          Fuel field is `block_fuel` (NOT `planned_fuel` — that does not exist).
        """
        url = f"{self.base_url}/api/pireps/prefile"
        flight = bid_data.get('flight', {})

        payload = {
            "flight_id":          flight.get('id'),
            "airline_id":         flight.get('airline_id'),
            "aircraft_id":        bid_data.get('aircraft_id') or flight.get('aircraft_id'),
            "flight_number":      flight.get('flight_number'),
            "dpt_airport_id":     flight.get('dpt_airport_id'),
            "arr_airport_id":     flight.get('arr_airport_id'),
            "planned_flight_time": flight.get('flight_time') or 0,
            "planned_distance":   float(flight.get('distance') or 0),
            "block_fuel":         planned_fuel,
            "level":              int(flight_level) if flight_level else 0,
            "route":              route,
            "flight_type":        flight.get('flight_type', 'J'),
            "source_name":        "Africana Tracker",
        }

        try:
            r = requests.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            self.current_pirep_id = r.json().get('data', {}).get('id')
            log.info("Flight prefiled — PIREP ID: %s", self.current_pirep_id)
            return self.current_pirep_id
        except Exception as e:
            log.error("Prefile failed: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                log.error("Server response: %s", e.response.text)
            return None

    # Internal phase codes → phpVMS v7 ACARS position 'status' strings.
    # These are stored on the Acars row (free-form string per PositionRequest.php
    # — phpVMS does NOT validate the value). They're only used for the live map
    # phase label; the real PIREP state is set via update_pirep_status().
    _V7_STATES = {
        "Brd": "boarding",
        "Txi": "taxi",
        "Dep": "takeoff",
        "Enr": "enroute",
        "App": "approach",
        "Lnd": "landed",
        "Pkd": "arrived",
    }

    def update_acars(self, lat, lon, alt, gs, heading, state="Enr",
                     vs=None):
        """
        Send a live position update to the phpVMS live map.

        phpVMS v7 PositionRequest (app/Http/Requests/Acars/PositionRequest.php):
          Required: lat, lon, positions[]
          Accepted per position: lat, lon, altitude, altitude_msl, altitude_agl,
            heading, vs, gs, ias, transponder, autopilot, fuel, fuel_flow,
            status (free-form), log, sim_time, created_at
          NOTE: per-position `distance` is NOT accepted — cumulative distance
          must be pushed via update_pirep_status() onto the PIREP itself.
        """
        if not self.current_pirep_id:
            return False

        url = f"{self.base_url}/api/pireps/{self.current_pirep_id}/acars/position"
        position = {
            "lat":      float(lat),
            "lon":      float(lon),
            "altitude": int(alt),
            "gs":       int(gs),
            "heading":  int(heading) % 360,
            "status":   self._V7_STATES.get(state, "enroute"),
        }
        if vs is not None:
            position["vs"] = int(vs)
        payload = {"positions": [position]}

        try:
            r = requests.post(url, headers=self.headers, json=payload, timeout=5)
            return r.status_code == 200
        except Exception as e:
            log.debug("ACARS update failed: %s", e)
            return False

    def update_pirep_status(self, status_code: str,
                            flight_time_min: float = None,
                            distance_nm: float = None) -> bool:
        """
        Update the PIREP's status, flight time, and distance via PUT /api/pireps/{id}.

        phpVMS v7 does NOT update status or accumulate flight stats from ACARS
        positions — these must be pushed explicitly.
        Valid PirepStatus codes (app/Models/Enums/PirepStatus.php):
          INI BST RDT PBT OFB DIR DIC GRT TXI TOF ICL TKO ENR DV TEN APR FIN
          LDG LAN ONB ARR DX EMG PSD
        flight_time_min: elapsed flight time in minutes (updates live map display).
        distance_nm: total distance flown in nautical miles (updates live map display).
        """
        if not self.current_pirep_id:
            return False
        payload = {"status": status_code}
        if flight_time_min is not None:
            payload["flight_time"] = int(flight_time_min)
        if distance_nm is not None:
            payload["distance"] = round(float(distance_nm), 2)
        try:
            r = requests.put(
                f"{self.base_url}/api/pireps/{self.current_pirep_id}",
                headers=self.headers,
                json=payload,
                timeout=5,
            )
            if r.status_code == 200:
                log.info("PIREP %s status → %s  ft=%.0fmin  dist=%.1fnm",
                         self.current_pirep_id, status_code,
                         flight_time_min or 0, distance_nm or 0)
                return True
            log.warning("PIREP status update got HTTP %s: %s",
                        r.status_code, r.text[:200])
            return False
        except Exception as e:
            log.debug("PIREP status update failed: %s", e)
            return False

    # PirepState enum (app/Models/Enums/PirepState.php):
    #   IN_PROGRESS=0, PENDING=1, ACCEPTED=2, CANCELLED=3,
    #   DELETED=4, DRAFT=5, REJECTED=6, PAUSED=7
    _ACTIVE_STATES = (0, 7)   # IN_PROGRESS or PAUSED

    def is_pirep_active(self) -> bool:
        """Return True if the current PIREP is still IN_PROGRESS or PAUSED on phpVMS."""
        if not self.current_pirep_id:
            return False
        try:
            r = requests.get(
                f"{self.base_url}/api/pireps/{self.current_pirep_id}",
                headers=self.headers, timeout=5,
            )
            if r.status_code != 200:
                log.warning("PIREP health check: HTTP %s for PIREP %s",
                            r.status_code, self.current_pirep_id)
                return False
            state = r.json().get("data", {}).get("state")
            active = state in self._ACTIVE_STATES
            if not active:
                log.warning("PIREP %s is no longer in progress (state=%s)",
                            self.current_pirep_id, state)
            return active
        except Exception as e:
            log.debug("PIREP health check failed: %s", e)
            return False

    def file_pirep(self, flight_time_min, fuel_used, distance_nm,
                   landing_rate=0, log_text=""):
        """
        File the final PIREP with actual flight data.

        phpVMS v7 FileRequest (app/Http/Requests/Acars/FileRequest.php):
          - REQUIRED: distance (numeric, in configured internal unit — nmi by default),
                      flight_time (integer minutes)
          - Optional: fuel_used, landing_rate, notes, block_time, source_name, …

        On success phpVMS sets state=PENDING and status=ARR (PirepService::file()),
        then submit() may auto-accept based on the user's rank flags.
        """
        if not self.current_pirep_id:
            return False

        url = f"{self.base_url}/api/pireps/{self.current_pirep_id}/file"
        payload = {
            "flight_time":  int(flight_time_min),
            "distance":     round(float(distance_nm), 2),
            "fuel_used":    float(fuel_used),
            "landing_rate": float(landing_rate),
            "notes":        log_text,
            "source_name":  "Africana Tracker",
        }

        try:
            r = requests.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            log.info("PIREP %s filed: %d min, %.1f nm, %.0f lbs fuel",
                     self.current_pirep_id, int(flight_time_min),
                     distance_nm, fuel_used)
            return True
        except Exception as e:
            log.error("PIREP filing failed: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                log.error("Server response: %s", e.response.text)
            return False
