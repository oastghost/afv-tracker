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
            "planned_flight_time": flight.get('flight_time', 0),
            "planned_fuel":       planned_fuel,
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

    # Internal phase codes → phpVMS v7 ACARS status strings
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
                     sim_time_min=0.0, distance_nm=0.0):
        """
        Send a live position update to the phpVMS live map.
        phpVMS v7 requires positions wrapped in an array under the 'positions' key,
        with a 'status' field (not 'state') containing the v7 state string.
        sim_time_min: elapsed flight time in minutes (shown as Flight Time on live map).
        distance_nm: total distance flown in nautical miles.
        """
        if not self.current_pirep_id:
            return False

        url = f"{self.base_url}/api/pireps/{self.current_pirep_id}/acars/position"
        payload = {
            "positions": [
                {
                    "lat":      float(lat),
                    "lon":      float(lon),
                    "altitude": int(alt),
                    "gs":       int(gs),
                    "heading":  int(heading),
                    "status":   self._V7_STATES.get(state, "enroute"),
                    "sim_time": round(float(sim_time_min), 1),
                    "distance": round(float(distance_nm), 2),
                }
            ]
        }

        try:
            r = requests.post(url, headers=self.headers, json=payload, timeout=5)
            return r.status_code == 200
        except Exception as e:
            log.debug("ACARS update failed: %s", e)
            return False

    def update_pirep_status(self, status_code: str) -> bool:
        """
        Update the PIREP's flight-phase status via PUT /api/pireps/{id}.

        phpVMS v7 does NOT update the PIREP status automatically from ACARS
        position data — positions are telemetry-only.  The status field must
        be set explicitly.  Valid codes: INI BRD DEP ENR APP LND ARR
        """
        if not self.current_pirep_id:
            return False
        try:
            r = requests.put(
                f"{self.base_url}/api/pireps/{self.current_pirep_id}",
                headers=self.headers,
                json={"status": status_code},
                timeout=5,
            )
            if r.status_code == 200:
                log.info("PIREP %s status → %s", self.current_pirep_id, status_code)
                return True
            log.warning("PIREP status update got HTTP %s: %s",
                        r.status_code, r.text[:200])
            return False
        except Exception as e:
            log.debug("PIREP status update failed: %s", e)
            return False

    def is_pirep_active(self) -> bool:
        """Return True if the current PIREP is still IN_PROGRESS (state=1) on phpVMS."""
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
            active = state in (1, 2)  # 1=IN_PROGRESS, 2=PAUSED
            if not active:
                log.warning("PIREP %s is no longer in progress (state=%s)",
                            self.current_pirep_id, state)
            return active
        except Exception as e:
            log.debug("PIREP health check failed: %s", e)
            return False

    def file_pirep(self, flight_time_min, fuel_used, landing_rate=0, log_text=""):
        """
        File the final PIREP with actual flight data.
        phpVMS v7 uses 'notes' (not 'log') for the free-text field.
        """
        if not self.current_pirep_id:
            return False

        url = f"{self.base_url}/api/pireps/{self.current_pirep_id}/file"
        payload = {
            "flight_time":  int(flight_time_min),
            "fuel_used":    float(fuel_used),
            "landing_rate": float(landing_rate),
            "notes":        log_text,
            "source_name":  "Africana Tracker",
        }

        try:
            r = requests.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            return True
        except Exception as e:
            log.error("PIREP filing failed: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                log.error("Server response: %s", e.response.text)
            return False
