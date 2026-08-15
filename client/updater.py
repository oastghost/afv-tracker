"""
AFV Tracker - Update Checker
Checks GitHub Releases for a version newer than the one currently running.
Never raises — any network hiccup or empty releases page just means
"no update found" so it can't crash the app or nag the user incorrectly.

This only *checks*; it deliberately doesn't self-replace the running exe
(Windows locks the file while it's running, and a half-applied silent
update is worse than asking the pilot to grab the new installer). The
caller is expected to point the pilot at the release page to download it.
"""

import logging
import re
from typing import Optional

import requests

from version import VERSION

log = logging.getLogger(__name__)

REPO = "oastghost/afv-tracker"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse_version(v: str) -> tuple:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3). Ignores anything non-numeric."""
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) or (0,)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_latest_release(current_version: str = VERSION) -> Optional[dict]:
    """
    Returns {"version", "url", "notes"} if a newer release is published on
    GitHub, else None. Requires the VA to actually publish a GitHub Release
    with a version tag (e.g. v1.2.3) for this to find anything.
    """
    try:
        r = requests.get(
            API_URL, timeout=6,
            headers={"Accept": "application/vnd.github+json"},
        )
        if r.status_code != 200:
            log.debug("Update check: GitHub returned HTTP %s", r.status_code)
            return None
        data = r.json()
        tag = data.get("tag_name", "")
        if not tag or not _is_newer(tag, current_version):
            return None
        return {
            "version": tag.lstrip("vV"),
            "url": data.get("html_url") or f"https://github.com/{REPO}/releases/latest",
            "notes": (data.get("body") or "")[:500],
        }
    except Exception as exc:
        log.debug("Update check failed (non-fatal): %s", exc)
        return None
