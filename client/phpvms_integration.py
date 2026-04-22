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
        # Initialize credentials on startup
        self.refresh_credentials()

    def refresh_credentials(self):
        """Reloads URL and Key from the config manager."""
        self.base_url = config.get("VA_URL", "https://africanava.ddns.net").rstrip('/')
        self.api_key = config.get("Pilot_Key", "")
        self.headers = {
            'X-API-Key': self.api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        log.info(f"phpVMS credentials refreshed for {self.base_url}")

    def test_connection(self):
        """Verifies if the API Key and URL are valid."""
        if not self.api_key:
            return False
        url = f"{self.base_url}/api/user"
        try:
            response = requests.get(url, headers=self.headers, timeout=5)
            return response.status_code == 200
        except:
            return False

    def get_bids(self):
        """Fetches active flight bookings (bids) for the pilot."""
        url = f"{self.base_url}/api/bids"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            log.error(f"Failed to fetch bids: {e}")
            return []

    def prefile_pirep(self, bid_data, planned_fuel, flight_level, route=""):
        """
        Takes the bid from the website and sends it to phpVMS as a prefiled flight.
        Handles the nested 'flight' object structure of phpVMS v7.
        """
        url = f"{self.base_url}/api/pireps/prefile"

        # Extract the nested flight details
        flight = bid_data.get('flight', {})

        payload = {
            "bid_id": bid_data.get('id'),
            "airline_id": flight.get('airline_id'),
            "aircraft_id": bid_data.get('aircraft_id') or flight.get('aircraft_id'),
            "flight_number": flight.get('flight_number'),
            "dpt_airport_id": flight.get('dpt_airport_id'),
            "arr_airport_id": flight.get('arr_airport_id'),
            "planned_fuel": planned_fuel,
            "level": int(flight_level),
            "route": route,
            "source_name": "Africana Tracker"
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            res_json = response.json()
            self.current_pirep_id = res_json['data']['id']
            log.info(f"Flight prefiled! PIREP ID: {self.current_pirep_id}")
            return self.current_pirep_id
        except Exception as e:
            logging.error(f"Prefile failed: {e}")
            if 'response' in locals():
                logging.error(f"Server Response: {response.text}")
            return None

    def update_acars(self, lat, lon, alt, gs, heading, state="ENR"):
        """Sends live telemetry to the phpVMS Live Map."""
        if not self.current_pirep_id:
            return False

        url = f"{self.base_url}/api/pireps/{self.current_pirep_id}/acars/position"
        payload = {
            "lat": lat,
            "lon": lon,
            "altitude": alt,
            "gs": gs,
            "heading": heading,
            "state": state
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=5)
            return response.status_code == 200
        except Exception as e:
            log.debug(f"ACARS update failed: {e}")
            return False

    def file_pirep(self, flight_time_min, fuel_used, landing_rate=0, log_text=""):
        """Finalizes the PIREP with actual flight data."""
        if not self.current_pirep_id:
            return False

        url = f"{self.base_url}/api/pireps/{self.current_pirep_id}/file"
        payload = {
            "flight_time": int(flight_time_min),
            "fuel_used": fuel_used,
            "landing_rate": landing_rate,
            "log": log_text
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            return response.status_code == 200
        except Exception as e:
            log.error(f"Filing failed: {e}")
            return False
