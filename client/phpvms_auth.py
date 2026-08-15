"""
AFV Tracker - phpVMS Credential Login (Stratos-style)

Lets the pilot sign in with their crew-centre email + password instead of
pasting an API key. phpVMS v7 has no password->key API endpoint, so this
module performs the same login a browser would (Laravel session + CSRF),
scrapes API-key candidates from the pilot's /profile page, and validates
each one against GET /api/user until one authenticates. Only the validated
key is stored — the password is never persisted.

Both entry points return the same shape:
    {"success": True,  "api_key": str, "user": dict}
    {"success": False, "error": str}
"""

import html
import logging
import re

import requests

log = logging.getLogger(__name__)

_UA = "AFV-Tracker (Windows; +https://africanava.ddns.net)"

# Laravel CSRF token on the login form: <input type="hidden" name="_token" value="...">
_CSRF_RE = re.compile(
    r'name=["\']_token["\']\s+value=["\']([^"\']+)["\']|'
    r'value=["\']([^"\']+)["\']\s+name=["\']_token["\']'
)

# Candidate API keys: phpVMS generates base62 strings (20-40 chars).
_TOKEN_RE = re.compile(r'\b([A-Za-z0-9]{20,48})\b')


def _fetch_user(base_url: str, api_key: str, timeout: int = 8):
    """GET /api/user with the key; returns the user dict on 200, else None."""
    try:
        r = requests.get(
            f"{base_url}/api/user",
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json().get("data", {}) or {}
    except Exception as exc:
        log.debug("Key validation request failed: %s", exc)
    return None


def validate_key(base_url: str, api_key: str) -> dict:
    """Direct API-key sign-in (the 'use API key instead' fallback path)."""
    base_url = (base_url or "").rstrip("/")
    api_key = (api_key or "").strip()
    if not base_url or not api_key:
        return {"success": False, "error": "Missing VA URL or API key."}
    user = _fetch_user(base_url, api_key)
    if user is None:
        return {"success": False,
                "error": "That API key was rejected by the VA server."}
    return {"success": True, "api_key": api_key, "user": user}


def login(base_url: str, email: str, password: str) -> dict:
    """Sign in with crew-centre credentials and recover the pilot's API key."""
    base_url = (base_url or "").rstrip("/")
    email = (email or "").strip()
    if not base_url:
        return {"success": False, "error": "VA URL is not configured."}
    if not email or not password:
        return {"success": False, "error": "Enter your email and password."}

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    # 1. Load the login form to obtain the session cookie + CSRF token.
    try:
        r = session.get(f"{base_url}/login", timeout=12)
        r.raise_for_status()
    except Exception as exc:
        log.warning("Login page unreachable: %s", exc)
        return {"success": False,
                "error": "Could not reach the VA website. Check your connection."}

    m = _CSRF_RE.search(r.text)
    token = (m.group(1) or m.group(2)) if m else None
    if not token:
        return {"success": False,
                "error": "Unexpected login page — is the VA URL correct?"}

    # 2. Post the credentials exactly as the browser form would.
    try:
        r = session.post(
            f"{base_url}/login",
            data={"_token": html.unescape(token),
                  "email": email, "password": password, "remember": "on"},
            timeout=12, allow_redirects=True,
        )
    except Exception as exc:
        log.warning("Login POST failed: %s", exc)
        return {"success": False, "error": "Login request failed — try again."}

    # Laravel bounces failed logins straight back to /login.
    if r.url.rstrip("/").endswith("/login") or r.status_code in (401, 403, 422):
        return {"success": False, "error": "Invalid email or password."}

    # 3. Scrape the profile page for API-key candidates.
    try:
        r = session.get(f"{base_url}/profile", timeout=12)
        r.raise_for_status()
    except Exception as exc:
        log.warning("Profile page fetch failed: %s", exc)
        return {"success": False,
                "error": "Signed in, but couldn't open your profile page."}

    page = r.text
    candidates, seen = [], set()
    # Tokens on lines that mention "api" are almost certainly the key —
    # try those first so we usually validate on the first network call.
    for line in page.splitlines():
        near_api = "api" in line.lower()
        for tok in _TOKEN_RE.findall(line):
            if tok in seen or tok.isdigit():
                continue
            seen.add(tok)
            (candidates.insert(0, tok) if near_api else candidates.append(tok))

    # 4. Validate candidates against the API until one works.
    for tok in candidates[:30]:
        user = _fetch_user(base_url, tok)
        if user is not None:
            log.info("Credential login OK for %s", user.get("name", email))
            return {"success": True, "api_key": tok, "user": user}

    return {"success": False,
            "error": "Signed in, but no API key was found on your profile page. "
                     "Paste your API key manually instead."}
