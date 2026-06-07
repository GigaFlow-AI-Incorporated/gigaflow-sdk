import gigaflow._auth as _auth


def test_access_token_returns_unexpired(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 1000)
    _auth.save_credentials({"access_token": "good", "refresh_token": "r",
                            "expires_at": 9999, "supabase_url": "https://p.supabase.co"})
    assert _auth.access_token("http://backend/api/v1") == "good"


def test_access_token_refreshes_when_expired(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 10_000)
    _auth.save_credentials({"access_token": "stale", "refresh_token": "r",
                            "expires_at": 5000, "email": "u@x.com",
                            "supabase_url": "https://p.supabase.co"})

    calls = {}

    def fake_refresh(supabase_url, anon_key, refresh_token):
        calls["args"] = (supabase_url, anon_key, refresh_token)
        return {"access_token": "fresh", "refresh_token": "r2", "expires_in": 3600}

    monkeypatch.setattr(_auth, "_supabase_refresh", fake_refresh)
    monkeypatch.setattr(_auth, "_fetch_auth_config",
                        lambda base: ("https://p.supabase.co", "anon-key"))

    token = _auth.access_token("http://backend/api/v1")
    assert token == "fresh"
    assert calls["args"] == ("https://p.supabase.co", "anon-key", "r")
    assert _auth.load_credentials()["access_token"] == "fresh"


def test_access_token_none_when_logged_out(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "none.json")
    assert _auth.access_token("http://backend/api/v1") is None


def test_refresh_failure_clears_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 10_000)
    _auth.save_credentials({"access_token": "stale", "refresh_token": "r",
                            "expires_at": 5000, "supabase_url": "https://p.supabase.co",
                            "anon_key": "anon-key"})
    monkeypatch.setattr(_auth, "_supabase_refresh", lambda *a: None)
    assert _auth.access_token("http://backend/api/v1") is None
    assert _auth.load_credentials() is None
