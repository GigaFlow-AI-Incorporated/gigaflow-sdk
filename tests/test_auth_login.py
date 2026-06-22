"""Tests for email-only waitlist login and token storage."""
import gigaflow._auth as _auth


def test_login_stores_credentials_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 1000)
    monkeypatch.setattr(
        _auth,
        "api",
        lambda base, method, path, body=None, **kw: (
            200,
            {"access_token": "AT", "email": "u@x.com", "expires_in": 3600},
        ),
    )

    ok, info = _auth.login("https://api.gigaflow.io/api/v1", "u@x.com")
    assert ok is True
    assert info["email"] == "u@x.com"
    saved = _auth.load_credentials()
    assert saved["access_token"] == "AT"
    assert saved["email"] == "u@x.com"
    assert saved["expires_at"] == 1000 + 3600
    # No Supabase fields persisted anymore.
    assert "refresh_token" not in saved


def test_login_accepts_201_created(monkeypatch, tmp_path):
    """The backend returns 201 Created on a successful POST /auth/login; the CLI
    must treat any 2xx as success, not only 200."""
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 1000)
    monkeypatch.setattr(
        _auth,
        "api",
        lambda base, method, path, body=None, **kw: (
            201,
            {"access_token": "AT", "email": "u@x.com", "expires_in": 3600},
        ),
    )

    ok, info = _auth.login("https://api.gigaflow.io/api/v1", "u@x.com")
    assert ok is True
    assert _auth.load_credentials()["access_token"] == "AT"


def test_login_not_on_allowlist_returns_code(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(
        _auth,
        "api",
        lambda base, method, path, body=None, **kw: (
            403,
            {"detail": {"code": "not_on_allowlist",
                        "book_a_demo_url": "https://gigaflow.io/?book-demo"}},
        ),
    )

    ok, info = _auth.login("https://api.gigaflow.io/api/v1", "nope@x.com")
    assert ok is False
    assert info["code"] == "not_on_allowlist"
    assert info["book_a_demo_url"] == "https://gigaflow.io/?book-demo"
    # Nothing stored on failure.
    assert _auth.load_credentials() is None


def test_access_token_returns_stored_until_expiry(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 1000)
    _auth.save_credentials({"access_token": "AT", "email": "u@x.com", "expires_at": 5000})
    assert _auth.access_token("https://api.gigaflow.io/api/v1") == "AT"


def test_access_token_none_when_expired(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 9999)
    _auth.save_credentials({"access_token": "AT", "email": "u@x.com", "expires_at": 5000})
    assert _auth.access_token("https://api.gigaflow.io/api/v1") is None


def test_auth_commands_register():
    import argparse

    from gigaflow.commands import auth
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    auth.register(sub)
    for name in ("login", "logout", "whoami"):
        ns = parser.parse_args([name])
        assert hasattr(ns, "func")
