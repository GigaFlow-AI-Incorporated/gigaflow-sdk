"""Tests for browser loopback login and auth commands."""
import threading
import urllib.request

import gigaflow._auth as _auth


def test_loopback_login_captures_matching_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 1000)
    # Avoid a real network call for Supabase config.
    monkeypatch.setattr(_auth, "_fetch_auth_config",
                        lambda base: ("https://p.supabase.co", "anon-key"))

    opened = {}

    def fake_open(url):
        opened["url"] = url
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        port, state = q["port"][0], q["state"][0]
        cb = (f"http://127.0.0.1:{port}/callback?state={state}"
              f"&access_token=AT&refresh_token=RT&expires_in=3600&email=u%40x.com")
        threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5)).start()

    monkeypatch.setattr(_auth.webbrowser, "open", fake_open)

    creds = _auth.run_loopback_login("https://api.gigaflow.io/api/v1", timeout=5)
    assert creds is not None
    assert creds["access_token"] == "AT"
    assert creds["refresh_token"] == "RT"
    assert creds["email"] == "u@x.com"
    assert creds["expires_at"] == 1000 + 3600
    assert creds["supabase_url"] == "https://p.supabase.co"
    assert "/cli-auth?" in opened["url"]
    assert _auth.load_credentials()["refresh_token"] == "RT"


def test_loopback_login_rejects_bad_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_fetch_auth_config",
                        lambda base: ("https://p.supabase.co", "anon-key"))

    def fake_open(url):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        port = q["port"][0]
        cb = (f"http://127.0.0.1:{port}/callback?state=WRONG"
              f"&access_token=AT&refresh_token=RT&expires_in=3600&email=u%40x.com")
        threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5)).start()

    monkeypatch.setattr(_auth.webbrowser, "open", fake_open)
    creds = _auth.run_loopback_login("https://api.gigaflow.io/api/v1", timeout=5)
    assert creds is None
    assert _auth.load_credentials() is None


def test_auth_commands_register():
    import argparse
    from gigaflow.commands import auth
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    auth.register(sub)
    # parse each subcommand and confirm a func is wired
    for name in ("login", "logout", "whoami"):
        ns = parser.parse_args([name])
        assert hasattr(ns, "func")
