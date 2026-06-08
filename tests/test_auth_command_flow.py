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
