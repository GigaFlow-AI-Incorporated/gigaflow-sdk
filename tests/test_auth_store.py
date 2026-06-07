import os
import stat

import gigaflow._auth as _auth


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "credentials.json")
    _auth.save_credentials({"access_token": "a", "refresh_token": "r",
                            "expires_at": 123, "email": "u@x.com",
                            "supabase_url": "https://p.supabase.co"})
    creds = _auth.load_credentials()
    assert creds["access_token"] == "a"
    assert creds["email"] == "u@x.com"


def test_save_sets_0600_perms(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", path)
    _auth.save_credentials({"access_token": "a"})
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "nope.json")
    assert _auth.load_credentials() is None


def test_clear_removes_file(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", path)
    _auth.save_credentials({"access_token": "a"})
    _auth.clear_credentials()
    assert not path.exists()
