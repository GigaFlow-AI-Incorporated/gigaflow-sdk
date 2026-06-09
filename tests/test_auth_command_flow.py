"""gigaflow login command: success message and not-allowlisted redirect."""
import gigaflow.commands.auth as auth_cmd


def test_login_command_success(monkeypatch, capsys):
    monkeypatch.setattr(auth_cmd._fmt, "prompt", lambda *a, **k: "u@x.com")
    monkeypatch.setattr(auth_cmd._auth, "login", lambda base, email: (True, {"email": email}))
    auth_cmd._handle_login(args=None, base_url="https://b/api/v1")
    out = capsys.readouterr().out
    assert "Signed in as u@x.com" in out


def test_login_command_not_on_allowlist_opens_book_demo(monkeypatch, capsys):
    monkeypatch.setattr(auth_cmd._fmt, "prompt", lambda *a, **k: "nope@x.com")
    monkeypatch.setattr(
        auth_cmd._auth,
        "login",
        lambda base, email: (
            False,
            {"code": "not_on_allowlist", "book_a_demo_url": "https://gigaflow.io/?book-demo"},
        ),
    )
    opened = {}
    monkeypatch.setattr(auth_cmd.webbrowser, "open", lambda url: opened.setdefault("url", url))
    auth_cmd._handle_login(args=None, base_url="https://b/api/v1")
    out = capsys.readouterr().out
    assert "book a demo" in out.lower()
    assert opened["url"] == "https://gigaflow.io/?book-demo"


def test_ensure_authenticated_returns_dev_key_without_login(monkeypatch):
    # An explicit dev key short-circuits — never prompts, never reads credentials.
    called = {}
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda base: called.setdefault("login", True))
    token = auth_cmd.ensure_authenticated("https://b/api/v1", api_key="dev-key")
    assert token == "dev-key"
    assert "login" not in called


def test_ensure_authenticated_uses_existing_token(monkeypatch):
    monkeypatch.setattr(auth_cmd._auth, "access_token", lambda base: "stored-jwt")
    monkeypatch.setattr(auth_cmd, "interactive_login",
                        lambda base: (_ for _ in ()).throw(AssertionError("should not log in")))
    token = auth_cmd.ensure_authenticated("https://b/api/v1", api_key=None)
    assert token == "stored-jwt"


def test_ensure_authenticated_logs_in_when_no_credential(monkeypatch):
    _it = iter([None, "fresh-jwt"])
    monkeypatch.setattr(auth_cmd._auth, "access_token",
                        lambda base: next(_it))  # before login: None, after: fresh
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda base: True)
    token = auth_cmd.ensure_authenticated("https://b/api/v1", api_key=None)
    assert token == "fresh-jwt"


def test_ensure_authenticated_returns_none_when_login_fails(monkeypatch):
    monkeypatch.setattr(auth_cmd._auth, "access_token", lambda base: None)
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda base: False)
    assert auth_cmd.ensure_authenticated("https://b/api/v1", api_key=None) is None
