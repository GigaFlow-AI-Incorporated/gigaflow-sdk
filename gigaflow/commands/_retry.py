"""Shared GET-with-retry for read-after-write lag on by-id endpoints."""
import time

from gigaflow._http import api


def get_with_retry(base_url, path, api_key=None, tries=5, delay=2.0):
    """GET that retries ONLY on 404 (eventual consistency right after a write).

    Non-404 statuses (including connection failures / other errors) return
    immediately. Returns the final (status, payload).
    """
    status, resp = api(base_url, "GET", path, api_key=api_key)
    attempt = 1
    while status == 404 and attempt < tries:
        time.sleep(delay)
        status, resp = api(base_url, "GET", path, api_key=api_key)
        attempt += 1
    return status, resp
