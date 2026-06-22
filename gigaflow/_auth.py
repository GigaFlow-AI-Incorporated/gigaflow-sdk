"""Per-user credentials for the CLI (email-only waitlist auth).

Stored in ~/.gigaflow/credentials.json (mode 0600). Holds the backend session
JWT obtained via `gigaflow login` (which POSTs an email to /auth/login). Token
values are never logged.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from gigaflow._http import api, ok

CREDENTIALS_PATH = Path.home() / ".gigaflow" / "credentials.json"

# Treat a token as expired this many seconds early to avoid edge-of-expiry 401s.
_EXPIRY_SKEW = 60


def _now() -> int:
    return int(time.time())


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


def login(base_url: str, email: str) -> tuple[bool, dict]:
    """POST {email} to /auth/login. On success store the token and return
    (True, {"email": ...}). On failure return (False, info) where info carries
    either {"code","book_a_demo_url"} for a not-allowlisted email, or
    {"error": ...} otherwise.
    """
    status, payload = api(base_url, "POST", "/auth/login", body={"email": email})
    if ok(status) and isinstance(payload, dict) and payload.get("access_token"):
        creds = {
            "access_token": payload["access_token"],
            "email": payload.get("email", email),
            "expires_at": _now() + int(payload.get("expires_in", 86400)),
        }
        save_credentials(creds)
        return True, {"email": creds["email"]}

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and detail.get("code"):
        return False, detail
    if status is None:
        reason = payload.get("error") if isinstance(payload, dict) else None
        return False, {"error": reason or "backend unreachable"}
    msg = detail if isinstance(detail, str) else (
        payload.get("error") if isinstance(payload, dict) else None
    )
    return False, {"error": msg or f"login failed (HTTP {status})"}


def access_token(base_url: str) -> str | None:
    """Return the stored session token if present and unexpired, else None.

    No refresh: the backend issues a fresh token on each `gigaflow login`. When
    the stored token is within _EXPIRY_SKEW of expiry, return None so the caller
    falls back to the "not signed in — run gigaflow login" path. ``base_url`` is
    accepted for call-site compatibility (cli.py) and intentionally unused.
    """
    creds = load_credentials()
    if not creds or not creds.get("access_token"):
        return None
    if _now() >= int(creds.get("expires_at", 0)) - _EXPIRY_SKEW:
        return None
    return creds["access_token"]
