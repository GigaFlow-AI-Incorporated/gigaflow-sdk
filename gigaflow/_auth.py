"""Per-user Supabase credentials for the CLI.

Stored separately from config.json in ~/.gigaflow/credentials.json (mode 0600).
Holds the Supabase session (access + refresh tokens) obtained via `gigaflow
login`. Token values are never logged.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from gigaflow._http import api

CREDENTIALS_PATH = Path.home() / ".gigaflow" / "credentials.json"


def load_credentials() -> dict | None:
    """Return the stored credentials dict, or None if not logged in."""
    if not CREDENTIALS_PATH.exists():
        return None
    try:
        with open(CREDENTIALS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_credentials(creds: dict) -> None:
    """Persist credentials with 0600 permissions, creating the dir if needed."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start (don't briefly expose a 0644 file).
    fd = os.open(CREDENTIALS_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CREDENTIALS_PATH, 0o600)


def clear_credentials() -> None:
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

# Refresh this many seconds before actual expiry to avoid edge-of-expiry 401s.
_EXPIRY_SKEW = 60


def _now() -> int:
    return int(time.time())


def _fetch_auth_config(base_url: str) -> tuple[str | None, str | None]:
    """GET {base_url}/auth/config → (supabase_url, supabase_anon_key)."""
    status, resp = api(base_url, "GET", "/auth/config")
    if status != 200 or not isinstance(resp, dict):
        return None, None
    return resp.get("supabase_url"), resp.get("supabase_anon_key")


def _supabase_refresh(supabase_url: str, anon_key: str, refresh_token: str) -> dict | None:
    """POST the Supabase refresh-token grant. Returns the token payload or None."""
    url = f"{supabase_url}/auth/v1/token?grant_type=refresh_token"
    body = json.dumps({"refresh_token": refresh_token}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("apikey", anon_key)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, ValueError):
        return None


def access_token(base_url: str) -> str | None:
    """Return a valid Supabase access token for the logged-in user, or None.

    Refreshes (and persists rotated tokens) when the stored token is within
    _EXPIRY_SKEW of expiry. On refresh failure, clears credentials and returns
    None so the caller falls back to the static key / login prompt.
    """
    creds = load_credentials()
    if not creds or not creds.get("access_token"):
        return None
    if _now() < int(creds.get("expires_at", 0)) - _EXPIRY_SKEW:
        return creds["access_token"]

    supabase_url = creds.get("supabase_url")
    anon_key = creds.get("anon_key")
    if not supabase_url or not anon_key:
        supabase_url, anon_key = _fetch_auth_config(base_url)
    if not supabase_url or not anon_key or not creds.get("refresh_token"):
        return creds.get("access_token")  # best effort; may 401 → handled upstream

    payload = _supabase_refresh(supabase_url, anon_key, creds["refresh_token"])
    if not payload or "access_token" not in payload:
        clear_credentials()
        return None

    creds.update({
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", creds["refresh_token"]),
        "expires_at": _now() + int(payload.get("expires_in", 3600)),
        "supabase_url": supabase_url,
        "anon_key": anon_key,
    })
    save_credentials(creds)
    return creds["access_token"]
