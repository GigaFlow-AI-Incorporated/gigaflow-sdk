# Email-only Waitlist Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken Supabase signup/login flow with a simple email-only waitlist: a manually-curated backend allowlist gates access, the CLI logs in by email alone, and not-yet-allowed users are pointed at the existing book-a-demo modal on gigaflow.io.

**Architecture:** Three phases across three repos, in dependency order. **Phase 1 (backend `gigaflow`)** adds an `allowlisted_emails` table and reworks `POST /api/v1/auth/login` to accept `{email}` only — allowlisted ⇒ find-or-create a `users` row and issue the existing HS256 session JWT; not allowlisted ⇒ `403 {code:"not_on_allowlist", book_a_demo_url}`. The gate is at login only; all existing JWT/`get_current_user` machinery is reused. **Phase 2 (CLI `gigaflow-sdk`)** rewrites `gigaflow login` to a `Waitlist email:` prompt that POSTs to `/auth/login`, stores the returned token, and on `not_on_allowlist` opens the book-a-demo URL; the Supabase browser-loopback is deleted. **Phase 3 (website `gigaflow-website`)** makes `?book-demo` auto-open the existing `SignupDialog` and retires the now-unused `/cli-auth` route.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + PyJWT (backend); stdlib-only Python + argparse + urllib (CLI); Vite + React + TypeScript + Vitest (website). Backend & CLI tests: pytest. Website tests: vitest (jsdom).

**Repo paths:**
- Backend: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow/backend`
- CLI: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk`
- Website: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-website`

**Per-repo branches / PRs (merge in order):**
1. backend → branch `feat/email-only-waitlist-login` → PR, merge first.
2. CLI → branch `feat/email-only-waitlist-login` → PR, merge second.
3. website → branch `feat/book-demo-deeplink` → PR, merge any time after backend.

> Each phase is implemented in its own git worktree + branch in that repo (per each repo's worktree policy). The backend is a thin dependency of the CLI, so it merges first.

**Out of scope (separate spec):** vendor-neutral onboarding / source-picker wizard (friction #1 & #3) — already being handled independently.

**Key assumption to confirm during Phase 1:** backend native auth is live on hosted `api.gigaflow.io` (`AUTH_JWT_SECRET` set in prod). Email-only login means anyone who knows an allowlisted email can sign in — accepted for a small trusted beta.

---

## Phase 1 — Backend (`gigaflow`)

Work in a worktree on branch `feat/email-only-waitlist-login` in
`/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow`.

Test runner: from `…/gigaflow/backend`, run `uv run pytest` (fall back to
`python -m pytest` if the repo isn't uv-managed). Tests mock the DB with
`AsyncMock` — no Postgres needed.

### Task 1: `AllowlistedEmail` model

**Files:**
- Create: `backend/app/models/allowlist.py`
- Test: `backend/tests/models/test_allowlist_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/models/test_allowlist_model.py
"""The allowlisted_emails model: citext PK email + added_at default."""
from app.models.allowlist import AllowlistedEmail


def test_allowlist_table_shape():
    t = AllowlistedEmail.__table__
    assert t.name == "allowlisted_emails"
    assert "email" in t.columns
    assert t.columns["email"].primary_key is True
    assert "added_at" in t.columns
    # added_at has a server default (now()).
    assert t.columns["added_at"].server_default is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/models/test_allowlist_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.allowlist'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/allowlist.py
"""Allowlisted emails — the manual access gate for email-only waitlist login.

One row per email allowed to log in. The operator grants access by inserting a
row (SQL one-liner). ``app/api/routers/auth.py`` checks this table at login and
issues a session JWT only when the email is present. citext PK gives
case-insensitive uniqueness for free (extension already enabled in migration
0003).
"""
from __future__ import annotations

from sqlalchemy import TIMESTAMP, Column, func
from sqlalchemy.dialects.postgresql import CITEXT

from app.db.base import Base


class AllowlistedEmail(Base):
    __tablename__ = "allowlisted_emails"

    email = Column(CITEXT(), primary_key=True)
    added_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/models/test_allowlist_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/allowlist.py backend/tests/models/test_allowlist_model.py
git commit -m "feat(backend): add AllowlistedEmail model"
```

### Task 2: Migration `0006` — allowlist table + nullable password_hash

> `origin/main` already has `0005_flow_run_tokenomics` (revision `0005`,
> down_revision `0004`), so this migration is `0006` chained onto `0005`.

**Files:**
- Create: `backend/alembic/versions/0006_allowlist_and_nullable_password.py`
- Modify: `backend/app/models/user.py:38` (make `password_hash` nullable)

> No unit test for the migration itself (matches the repo — `0003`/`0004` have
> none). The model edit is covered by Task 3's login tests creating a
> password-less user. Verify the migration imports cleanly with Alembic.

- [ ] **Step 1: Make `password_hash` nullable in the model**

In `backend/app/models/user.py`, change line 38 from:

```python
    password_hash = Column(String, nullable=False)
```

to:

```python
    # Nullable: email-only waitlist logins create a row with no password.
    password_hash = Column(String, nullable=True)
```

- [ ] **Step 2: Write the migration**

```python
# backend/alembic/versions/0006_allowlist_and_nullable_password.py
"""allowlisted_emails table + make users.password_hash nullable

Email-only waitlist access: ``allowlisted_emails`` is the manual access gate
(``app/api/routers/auth.py`` checks it at login). Password-less rows are created
for allowlisted emails on first login, so ``users.password_hash`` becomes
nullable. citext is already enabled (migration 0003).
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allowlisted_emails",
        sa.Column("email", CITEXT(), primary_key=True),
        sa.Column(
            "added_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Backfill any null hashes before re-imposing NOT NULL so the alter can't fail.
    op.execute("DELETE FROM users WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
    op.drop_table("allowlisted_emails")
```

- [ ] **Step 3: Verify the migration module imports**

Run: `cd backend && uv run python -c "import importlib.util, glob; f=glob.glob('alembic/versions/0006_*.py')[0]; s=importlib.util.spec_from_file_location('m', f); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.revision, m.down_revision)"`
Expected: prints `0006 0005`

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0006_allowlist_and_nullable_password.py backend/app/models/user.py
git commit -m "feat(backend): migration 0006 — allowlist table + nullable password_hash"
```

### Task 3: Rework `POST /auth/login` to email-only allowlist

**Files:**
- Modify: `backend/app/api/routers/auth.py` (replace `LoginRequest` + `login`, add `_book_a_demo_url`, trim imports)
- Modify: `backend/tests/api/test_auth_endpoints.py` (replace the three password-login tests with allowlist tests)

- [ ] **Step 1: Replace the login tests (write the failing tests)**

In `backend/tests/api/test_auth_endpoints.py`, **delete** the three existing
login tests: `test_login_success_sets_cookie_and_updates_last_login`,
`test_login_unknown_email_and_wrong_password_identical_401`, and
`test_login_inactive_user_401` (lines 184–244). Replace them with:

```python
# ── login (email-only allowlist) ──────────────────────────────────────────────

def _allowlist_then_user_db(allowed_row, user_row, refreshed_id=None):
    """A DB whose two execute() calls return: (1) the allowlist lookup, then
    (2) the users lookup. refresh() can backfill an id for a freshly-added user."""
    db = _base_db()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(allowed_row), _scalar_result(user_row)]
    )

    async def _refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = refreshed_id or uuid4()

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


@pytest.mark.asyncio
async def test_login_not_on_allowlist_returns_403_with_code():
    db = _base_db()
    db.execute = AsyncMock(return_value=_scalar_result(None))  # allowlist miss
    async with _make_client(db) as c:
        resp = await c.post(f"{BASE}/auth/login", json={"email": "nope@example.com"})
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "not_on_allowlist"
    assert detail["book_a_demo_url"].endswith("/?book-demo")
    # No session cookie issued.
    assert "gigaflow_session=" not in resp.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_login_allowlisted_existing_user_returns_token():
    user = _user_row(email="member@example.com")
    db = _allowlist_then_user_db(allowed_row=MagicMock(), user_row=user)
    async with _make_client(db) as c:
        resp = await c.post(f"{BASE}/auth/login", json={"email": "member@example.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "member@example.com"
    assert body["access_token"]
    assert body["expires_in"] == settings.AUTH_JWT_EXP_SECONDS
    assert "gigaflow_session=" in resp.headers.get("set-cookie", "")
    assert user.last_login_at is not None


@pytest.mark.asyncio
async def test_login_allowlisted_new_email_creates_user():
    db = _allowlist_then_user_db(allowed_row=MagicMock(), user_row=None)
    captured = {}
    db.add = MagicMock(side_effect=lambda obj: captured.setdefault("user", obj))
    async with _make_client(db) as c:
        resp = await c.post(f"{BASE}/auth/login", json={"email": "fresh@example.com"})
    assert resp.status_code == 200, resp.text
    db.add.assert_called_once()
    assert captured["user"].email == "fresh@example.com"
    assert resp.json()["access_token"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/api/test_auth_endpoints.py -k login -v`
Expected: FAIL — current `/login` requires a `password` field (422) and has no allowlist check.

- [ ] **Step 3: Rework the login endpoint**

In `backend/app/api/routers/auth.py`:

(a) Replace the imports block for security helpers (lines 40) — `verify_password`
and `needs_rehash` are no longer used by login; keep `hash_password` (used by
signup):

```python
from app.core.security import hash_password
```

(b) Add the allowlist model import next to the `User` import (line 42):

```python
from app.models.allowlist import AllowlistedEmail
from app.models.user import User
```

(c) Replace the `LoginRequest` class (lines 63–65) with an email-only model:

```python
class LoginRequest(BaseModel):
    email: EmailStr
```

(d) Add this helper just below `_validate_password` (after line 92):

```python
def _book_a_demo_url() -> str:
    """The website book-a-demo deep link returned to not-allowlisted callers."""
    base = (settings.WEBSITE_URL or "https://gigaflow.io").rstrip("/")
    return f"{base}/?book-demo"
```

(e) Replace the entire `login` function (lines 134–181) with:

```python
@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_traces_db),
) -> dict:
    """Email-only waitlist login.

    If the email is on ``allowlisted_emails`` we find-or-create a (password-less)
    ``users`` row and issue the session JWT — returned BOTH as an httpOnly cookie
    (browser) and in the body (CLI). If not allowlisted, 403 with a structured
    body pointing at the book-a-demo page. The gate is here at login only.
    """
    require_auth_configured()
    email = body.email.strip()

    allowed = (
        await db.execute(
            select(AllowlistedEmail).filter(AllowlistedEmail.email == email).limit(1)
        )
    ).scalars().first()
    if allowed is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_on_allowlist", "book_a_demo_url": _book_a_demo_url()},
        )

    user = (
        await db.execute(select(User).filter(User.email == email).limit(1))
    ).scalars().first()
    if user is None:
        user = User(email=email)  # password-less waitlist account
        db.add(user)
        await db.commit()
        await db.refresh(user)

    from sqlalchemy import func

    user.last_login_at = func.now()
    await db.commit()
    await db.refresh(user)

    token = issue_session_jwt(user.id)
    _set_session_cookie(response, token)
    logger.info("auth.login(waitlist): user id=%s", user.id)
    return {
        "access_token": token,
        "email": str(user.email),
        "expires_in": settings.AUTH_JWT_EXP_SECONDS,
    }
```

(f) Remove the now-unused `_DUMMY_HASH` constant (lines 51–55) and its
explanatory comment — it was only used by the old password-login branch.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_auth_endpoints.py -v`
Expected: PASS (signup, /me, logout tests unaffected; the three new login tests pass)

- [ ] **Step 5: Lint**

Run: `cd backend && uv run ruff check app/api/routers/auth.py`
Expected: no unused-import or other errors (confirms the import trims are right)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routers/auth.py backend/tests/api/test_auth_endpoints.py
git commit -m "feat(backend): email-only allowlist login (drop password on /auth/login)"
```

### Task 4: Document the manual allowlist action

**Files:**
- Modify: `backend/app/models/allowlist.py` (docstring already covers it — add a runbook note to the backend README if one exists; otherwise this task is the SQL snippet below committed as a comment)

- [ ] **Step 1: Confirm the grant-access SQL**

The operator grants access with a single statement (psql against the traces DB):

```sql
INSERT INTO allowlisted_emails (email) VALUES ('person@company.com')
ON CONFLICT (email) DO NOTHING;
```

Revoke:

```sql
DELETE FROM allowlisted_emails WHERE email = 'person@company.com';
```

- [ ] **Step 2: Add the runbook note**

If `backend/README.md` exists, add a short "## Granting waitlist access" section
containing the two SQL statements above. If it does not exist, skip — the model
docstring already documents the mechanism.

- [ ] **Step 3: Commit (only if a file changed)**

```bash
git add backend/README.md
git commit -m "docs(backend): how to grant/revoke waitlist access"
```

---

## Phase 2 — CLI (`gigaflow-sdk`)

Work in a worktree on branch `feat/email-only-waitlist-login`.
Test runner from the CLI repo root: `uv run pytest`. Lint: `uv run ruff check .`.

### Task 5: Add `_auth.login()` and simplify `access_token()`; delete Supabase loopback

**Files:**
- Modify: `gigaflow/_auth.py` (rewrite — add `login`, simplify `access_token`, delete loopback/refresh/config-fetch)
- Test: `tests/test_auth_login.py` (replace), `tests/test_auth_refresh.py` (delete)

- [ ] **Step 1: Replace `tests/test_auth_login.py` (write the failing tests)**

```python
# tests/test_auth_login.py
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
```

- [ ] **Step 2: Delete the obsolete refresh test**

```bash
git rm tests/test_auth_refresh.py
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_login.py -v`
Expected: FAIL — `_auth.login` does not exist; `access_token` still tries Supabase refresh.

- [ ] **Step 4: Rewrite `gigaflow/_auth.py`**

Replace the entire file with:

```python
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

from gigaflow._http import api

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
    if status == 200 and isinstance(payload, dict) and payload.get("access_token"):
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_login.py tests/test_auth_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add gigaflow/_auth.py tests/test_auth_login.py
git rm --cached tests/test_auth_refresh.py 2>/dev/null; true
git commit -m "feat(cli): email-only login + simplified token store; drop Supabase loopback"
```

### Task 6: Rewrite `gigaflow login` / `whoami` command handlers

**Files:**
- Modify: `gigaflow/commands/auth.py`
- Test: `tests/test_commands.py` (add a login-flow test) — or create `tests/test_auth_command_flow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_command_flow.py
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
    assert "join the waitlist" in out.lower()
    assert opened["url"] == "https://gigaflow.io/?book-demo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth_command_flow.py -v`
Expected: FAIL — `_handle_login` still calls `run_loopback_login`; `webbrowser` not imported in the module.

- [ ] **Step 3: Rewrite `gigaflow/commands/auth.py`**

```python
"""login / logout / whoami — email-only waitlist auth for the CLI."""
import webbrowser

from gigaflow import _auth, _fmt

_DEFAULT_BOOK_A_DEMO = "https://gigaflow.io/?book-demo"


def register(sub) -> None:
    sub.add_parser("login", help="Sign in with your waitlist email").set_defaults(func=_handle_login)
    sub.add_parser("logout", help="Clear stored credentials").set_defaults(func=_handle_logout)
    sub.add_parser("whoami", help="Show the signed-in account").set_defaults(func=_handle_whoami)


def _handle_login(args, base_url: str) -> None:
    _fmt.header("GigaFlow Login")
    email = _fmt.prompt("Waitlist email", required=True)
    ok, info = _auth.login(base_url, email)
    if ok:
        _fmt.ok(f"Signed in as {info.get('email', email)}")
        return
    if info.get("code") == "not_on_allowlist":
        url = info.get("book_a_demo_url", _DEFAULT_BOOK_A_DEMO)
        _fmt.fail("That email isn't on the waitlist yet.")
        _fmt.info(f"Want to join the waitlist? Book a demo: {url}")
        webbrowser.open(url)
        return
    _fmt.fail(f"Login failed: {info.get('error', 'unknown error')}")


def _handle_logout(args, base_url: str) -> None:
    _auth.clear_credentials()
    _fmt.ok("Signed out.")


def _handle_whoami(args, base_url: str) -> None:
    creds = _auth.load_credentials()
    if not creds:
        _fmt.info("Not signed in. Run: gigaflow login")
        return
    _fmt.info(f"Signed in as {creds.get('email', '(unknown email)')}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_auth_command_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/auth.py tests/test_auth_command_flow.py
git commit -m "feat(cli): Waitlist email prompt + book-a-demo redirect on not-allowlisted"
```

### Task 7: Update the "not signed in" hint and `auth_error_hint`

**Files:**
- Modify: `gigaflow/cli.py:163` (the not-signed-in stderr message — drop "opens your browser")
- Modify: `gigaflow/_http.py:93-98` (`auth_error_hint`)
- Test: `tests/test_hosted_backend.py` or `tests/test_commands.py` — assert the new hint text (only if an existing test asserts the old string; otherwise no test change)

- [ ] **Step 1: Check whether any test asserts the old strings**

Run: `grep -rn "opens your browser\|gigaflow setup'" tests/`
Expected: note any matches; if a test asserts the old wording, update it in Step 3.

- [ ] **Step 2: Update the messages**

In `gigaflow/cli.py` line 163, change:

```python
        print("  You're not signed in. Run: gigaflow login  (opens your browser to sign in)", file=sys.stderr)
```

to:

```python
        print("  You're not signed in. Run: gigaflow login  (sign in with your waitlist email)", file=sys.stderr)
```

In `gigaflow/_http.py`, update `auth_error_hint` (lines 93–98):

```python
def auth_error_hint() -> str:
    """One-line, actionable message for a 401/403 from the backend."""
    return (
        "Authentication failed — run 'gigaflow login' with your waitlist email, "
        "or set GIGAFLOW_API_KEY / pass --api-key."
    )
```

- [ ] **Step 3: Update any test asserting the old wording**

If Step 1 found matches, change those assertions to the new substrings
(`"sign in with your waitlist email"` / `"gigaflow login"`).

- [ ] **Step 4: Run the full CLI test suite**

Run: `uv run pytest -q`
Expected: PASS. (Confirms `test_cli_credential_precedence.py` still passes —
`access_token` keeps its `(base_url)` signature and still returns the stored
token, so credential precedence is unchanged.)

- [ ] **Step 5: Lint**

Run: `uv run ruff check .`
Expected: clean (no leftover unused imports from the `_auth.py` rewrite).

- [ ] **Step 6: Commit**

```bash
git add gigaflow/cli.py gigaflow/_http.py tests/
git commit -m "chore(cli): update auth hints for waitlist login"
```

### Task 8: Manual end-to-end smoke (CLI ↔ backend)

**Files:** none (verification only)

- [ ] **Step 1: Run the backend locally with auth on**

In the backend repo: `cd backend && GIGAFLOW_DEV_MODE=false AUTH_JWT_SECRET=dev-secret-32-bytes-minimum-长够 uv run uvicorn app.main:app --port 8000` (or `docker compose up`). Insert one allowlisted email:
`psql … -c "INSERT INTO allowlisted_emails (email) VALUES ('me@example.com');"`

- [ ] **Step 2: Log in via the editable CLI**

Run: `gigaflow --backend http://localhost:8000/api/v1 login` → enter `me@example.com`.
Expected: `Signed in as me@example.com`; `~/.gigaflow/credentials.json` contains `access_token` + `email`.

- [ ] **Step 3: Log in with a non-allowlisted email**

Run: `gigaflow --backend http://localhost:8000/api/v1 login` → enter `nobody@example.com`.
Expected: "That email isn't on the waitlist yet." + book-a-demo line; browser opens `…/?book-demo`.

- [ ] **Step 4: whoami / logout**

Run: `gigaflow whoami` → `Signed in as me@example.com`; then `gigaflow logout` → `Signed out.`; `gigaflow whoami` → `Not signed in.`

---

## Phase 3 — Website (`gigaflow-website`)

Work in a worktree on branch `feat/book-demo-deeplink`.
Test runner from the website repo root: `npm run test` (vitest). Build check:
`npm run build`.

### Task 9: Auto-open the book-a-demo modal on `?book-demo`

**Files:**
- Modify: `src/contexts/SignupContext.tsx`
- Test: `src/contexts/SignupContext.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/contexts/SignupContext.test.tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SignupProvider, useSignup } from "./SignupContext";

function Probe() {
  const { open } = useSignup();
  return <span>{open ? "open" : "closed"}</span>;
}

describe("SignupProvider ?book-demo deep link", () => {
  it("opens the dialog when ?book-demo is present", () => {
    window.history.pushState({}, "", "/?book-demo");
    render(
      <SignupProvider>
        <Probe />
      </SignupProvider>,
    );
    expect(screen.getByText("open")).toBeTruthy();
  });

  it("stays closed without the param", () => {
    window.history.pushState({}, "", "/");
    render(
      <SignupProvider>
        <Probe />
      </SignupProvider>,
    );
    expect(screen.getByText("closed")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/contexts/SignupContext.test.tsx`
Expected: FAIL — first case renders "closed" (provider always initialises `open=false`).

- [ ] **Step 3: Initialise `open` from the URL param**

In `src/contexts/SignupContext.tsx`, replace the `useState(false)` line in
`SignupProvider` with a lazy initialiser that reads the query string:

```tsx
  const [open, setOpen] = useState<boolean>(
    () =>
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).has("book-demo"),
  );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/contexts/SignupContext.test.tsx`
Expected: PASS (both cases)

- [ ] **Step 5: Commit**

```bash
git add src/contexts/SignupContext.tsx src/contexts/SignupContext.test.tsx
git commit -m "feat(website): auto-open book-a-demo modal on ?book-demo"
```

### Task 10: Retire the unused `/cli-auth` route

**Files:**
- Modify: `src/App.tsx` (remove the `/cli-auth` branch + the `CliAuth` import)
- Delete: `src/components/CliAuth.tsx`

> The CLI no longer uses the Supabase browser handoff (Phase 2). `AuthProvider`
> / `AuthContext` stay — they back the "Analyze a trace" feature, which is
> unrelated to CLI login.

- [ ] **Step 1: Confirm `CliAuth` has no other importers**

Run: `grep -rn "CliAuth" src/ | grep -v "src/components/CliAuth.tsx"`
Expected: only `src/App.tsx` references it.

- [ ] **Step 2: Remove the route and import from `src/App.tsx`**

Delete the import line:

```tsx
import CliAuth from "./components/CliAuth";
```

and delete the entire early-return block in `App()`:

```tsx
  if (typeof window !== "undefined" && window.location.pathname === "/cli-auth") {
    return (
      <AuthProvider>
        <CliAuth />
      </AuthProvider>
    );
  }
```

- [ ] **Step 3: Delete the component**

```bash
git rm src/components/CliAuth.tsx
```

- [ ] **Step 4: Verify build + tests**

Run: `npm run build && npm run test`
Expected: build succeeds with no unresolved imports; tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx
git commit -m "chore(website): remove unused /cli-auth route + CliAuth component"
```

---

## Self-Review

**Spec coverage** (every spec section maps to a task):
- Backend `allowlisted_emails` table → Task 1 (model) + Task 2 (migration). ✓
- `POST /auth/login {email}`: allowlist check, 403 `not_on_allowlist`, find-or-create user, issue JWT (cookie + body), `/me` unchanged → Task 3. ✓
- `users.password_hash` nullable → Task 2. ✓
- Manual allowlist knob (SQL) → Task 4. ✓
- CLI `Waitlist email:` prompt, store token, friendly book-a-demo redirect → Tasks 5–6. ✓
- Delete Supabase loopback / `_fetch_auth_config` / `_supabase_refresh` / `run_loopback_login` → Task 5. ✓
- `whoami` shows email; `logout` unchanged → Task 6. ✓
- Token handling without refresh → Task 5 (`access_token`). ✓
- Friendly 403 / not-signed-in hints → Task 7. ✓
- Website `?book-demo` deep link → Task 9. ✓
- Retire `/cli-auth` → Task 10. ✓
- `GET /auth/me` already exists in the backend (returns `{id,email,created_at}`) — no new task needed; `whoami` reads stored creds offline by design. ✓

**Notes on decisions:**
- The spec mentioned adding `GET /auth/me`; it already exists (`auth.py:197`), so the plan reuses it and `whoami` stays offline (reads `credentials.json`). No gap.
- `/signup` is left dormant (still password-based, still tested) rather than removed — minimal churn, matches "removed or left dormant."

**Placeholder scan:** none — every code/test step contains complete code and exact commands.

**Type/name consistency:** `_auth.login(base_url, email) -> (bool, dict)` is defined in Task 5 and consumed identically in Task 6's handler and tests. `access_token(base_url)` keeps its signature (Task 5) so `cli.py:151` is unchanged (Task 7 verified). The 403 body shape `{"code","book_a_demo_url"}` is produced in Task 3 and consumed in Tasks 5–6. `?book-demo` is the single agreed param across backend `_book_a_demo_url`, CLI default, and website Task 9.
