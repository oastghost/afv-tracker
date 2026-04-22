"""
AFV Tracker - Configuration Manager
Handles local config persistence (pilot ID, preferences, etc.)
"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.path.expanduser("~")) / ".afv_tracker" / "config.json"

DEFAULTS = {
    "vatsim_cid":   "",          # VATSIM CID (primary identifier sent to server)
    "simbrief_id":  "",          # SimBrief username or numeric pilot ID
    "pilot_name":   "",          # Display name
    "discord":      "",          # Discord handle (e.g. username#0000 or just username)
    "server_url":   "http://localhost:8000",
    "simconnect_poll_interval": 5,
    "weight_unit":  "LBS",       # "LBS" or "KG"
    "theme":        "dark",
    "VA_URL":  "https://africanava.ddns.net",
    "Pilot_Key":    "",
}


def load_config() -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            # Merge with defaults so new keys always appear
            merged = {**DEFAULTS, **data}
            # Migrate old pilot_id / simbrief_username keys
            if not merged["vatsim_cid"] and data.get("pilot_id"):
                merged["vatsim_cid"] = data["pilot_id"]
            if not merged["simbrief_id"] and data.get("simbrief_username"):
                merged["simbrief_id"] = data["simbrief_username"]
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULTS)


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str, default=None):
    cfg = load_config()
    return cfg.get(key, default)


def set_value(key: str, value) -> None:
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
