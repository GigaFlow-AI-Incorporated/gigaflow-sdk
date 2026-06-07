# Per-user CLI Accounts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the gigaflow CLI a per-user Supabase identity (`gigaflow login` via browser loopback handoff) so every trace it uploads is owned by that account and the web UI shows only that user's traces.

**Architecture:** Three repos. **Backend** (`gigaflow`, FastAPI) gains a `Project.user_id` owner column, a public `/auth/config` endpoint, identity-aware auth on the customer routers, and read/write scoping by owner. **SDK** (`gigaflow-sdk`, stdlib-only Python CLI) gains `gigaflow login/logout/whoami`, a `~/.gigaflow/credentials.json` token store with refresh, a one-shot loopback callback server, and credential precedence wiring. **Website** (`gigaflow-website`, Vite+React) gains email+password auth methods and a `/cli-auth` handoff page that redirects the Supabase session to the CLI's loopback port. Each phase is independently shippable: the static service key + `GIGAFLOW_DEV_MODE` remain working fallbacks throughout.

**Tech Stack:** Python 3.10+ (stdlib only on the SDK), FastAPI + SQLAlchemy async + Alembic + pydantic-settings (backend, run via `uv run`), React + TypeScript + Vite + Vitest + Supabase JS (website). Supabase Auth = identity provider; app data in RDS Postgres.

**Repo roots (absolute):**
- Backend: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow`
- SDK: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk`
- Website: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-website`

**Spec:** `gigaflow-sdk/docs/superpowers/specs/2026-06-07-cli-user-accounts-design.md`

**Commands:** Backend tests `uv run pytest` (from `gigaflow/backend`); migrations `uv run alembic upgrade head`. SDK tests `uv run pytest` (from `gigaflow-sdk`). Website tests `npm run test`, lint `npm run lint` (from `gigaflow-website`).

---

## File Structure

### Backend (`gigaflow/backend`)
- Modify `app/models/project.py` — add `user_id` owner column.
- Create `alembic/versions/0003_project_owner.py` — migration for the column + index.
- Modify `app/core/config.py` — add `SUPABASE_URL`, `SUPABASE_ANON_KEY` settings.
- Create `app/api/routers/auth_config.py` — public `GET /auth/config`.
- Modify `app/main.py` — mount `auth_config` router (public); swap `_customer_api_deps` to identity-aware auth.
- Modify `app/api/routers/projects.py` — stamp owner on create; scope list/get by owner.
- Modify `app/api/routers/traces.py` — scope list/get by owner.
- Create `app/services/ownership.py` — `owner_of_project()` helper shared by ingest paths.
- Modify `app/api/routers/otlp.py` and the datasource-sync trace-creation path — stamp `Trace.user_id` from the project owner.
- Tests under `backend/tests/api/` and `backend/tests/`.

### SDK (`gigaflow-sdk`)
- Create `gigaflow/_auth.py` — credential store + token refresh + loopback login helpers.
- Create `gigaflow/commands/auth.py` — `login` / `logout` / `whoami` commands.
- Modify `gigaflow/cli.py` — register `auth` commands; wire credential precedence; first-run hint.
- Tests under `tests/`.

### Website (`gigaflow-website`)
- Modify `src/contexts/AuthContext.tsx` — add `signInWithPassword`, `signUp`.
- Create `src/components/CliAuth.tsx` — the `/cli-auth` handoff page.
- Modify `src/App.tsx` — render `CliAuth` when `pathname === "/cli-auth"`.
- Tests `src/contexts/AuthContext.test.tsx` (new) and `src/components/CliAuth.test.tsx` (new).

### Manual / config (Phase D)
- Supabase dashboard: enable email+password provider + email confirmation.
- Backend env: set `SUPABASE_URL`, `SUPABASE_ANON_KEY` (and existing `SUPABASE_JWKS_URL`/secret).
- Hosting: SPA-fallback `/cli-auth` → `index.html`.

---

# Phase A — Backend (ship first)

Everything here is backward compatible: the static `FLOW_COMPUTE_API_KEY` still authenticates as an unscoped service caller, and `GIGAFLOW_DEV_MODE=true` still bypasses auth. New behavior only triggers when a real Supabase user JWT is presented.

### Task A1: Add `Project.user_id` owner column + migration

**Files:**
- Modify: `gigaflow/backend/app/models/project.py`
- Create: `gigaflow/backend/alembic/versions/0003_project_owner.py`
- Test: `gigaflow/backend/tests/test_project_owner_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow/backend/tests/test_project_owner_migration.py
"""The Project model must expose a nullable, indexed user_id owner column."""
from app.models.project import Project


def test_project_has_user_id_column():
    col = Project.__table__.columns["user_id"]
    assert col.nullable is True
    assert col.index is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow/backend && uv run pytest tests/test_project_owner_migration.py -v`
Expected: FAIL — `KeyError: 'user_id'`.

- [ ] **Step 3: Add the column to the model**

In `app/models/project.py`, add the import and column. The existing `Column`/`UUID` imports are already present; add `user_id` right after `name`:

```python
    name = Column(String(255), nullable=False)
    # Owner — the Supabase user (sub UUID) who created this project. NULL for
    # legacy/service-created projects. Indexed for owner-scoped list queries.
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow/backend && uv run pytest tests/test_project_owner_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Write the Alembic migration**

```python
# gigaflow/backend/alembic/versions/0003_project_owner.py
"""add project.user_id owner column"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_projects_user_id", "projects", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_column("projects", "user_id")
```

- [ ] **Step 6: Apply the migration against a dev DB**

Run: `cd gigaflow/backend && uv run alembic upgrade head`
Expected: `Running upgrade 0002 -> 0003, add project.user_id owner column`.

- [ ] **Step 7: Commit**

```bash
cd gigaflow
git add backend/app/models/project.py backend/alembic/versions/0003_project_owner.py backend/tests/test_project_owner_migration.py
git commit -m "feat(backend): add Project.user_id owner column + migration"
```

---

### Task A2: Public `/auth/config` endpoint + Supabase settings

The CLI needs the Supabase project URL + anon key to refresh tokens. Expose them from a public endpoint (anon key is RLS-gated and safe to ship).

**Files:**
- Modify: `gigaflow/backend/app/core/config.py`
- Create: `gigaflow/backend/app/api/routers/auth_config.py`
- Modify: `gigaflow/backend/app/main.py`
- Test: `gigaflow/backend/tests/api/test_auth_config.py`

- [ ] **Step 1: Add settings fields**

In `app/core/config.py`, beside the existing `SUPABASE_JWT_*` fields, add:

```python
    # Public Supabase project URL + anon key, served to the CLI via
    # GET /api/v1/auth/config so it can run the password/refresh-token grants.
    # The anon key is RLS-gated and intended for clients — safe to expose.
    SUPABASE_URL: str | None = None
    SUPABASE_ANON_KEY: str | None = None
```

- [ ] **Step 2: Write the failing test**

```python
# gigaflow/backend/tests/api/test_auth_config.py
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers import auth_config


@pytest.fixture
def client(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon-123")
    app = FastAPI()
    app.include_router(auth_config.router, prefix="/api/v1/auth")
    return app


async def test_auth_config_returns_url_and_anon_key(client):
    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://t") as c:
        resp = await c.get("/api/v1/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "supabase_url": "https://proj.supabase.co",
        "supabase_anon_key": "anon-123",
    }
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_auth_config.py -v`
Expected: FAIL — `ImportError` / no `auth_config` module.

- [ ] **Step 4: Implement the router**

```python
# gigaflow/backend/app/api/routers/auth_config.py
"""Public endpoint exposing the Supabase URL + anon key to the CLI.

The CLI uses these to run the Supabase password / refresh-token grants during
`gigaflow login`. The anon key is RLS-gated and meant for clients, so this
endpoint is intentionally unauthenticated (mounted outside the customer-API
auth gate in app.main).
"""
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/config")
async def auth_config() -> dict:
    return {
        "supabase_url": settings.SUPABASE_URL,
        "supabase_anon_key": settings.SUPABASE_ANON_KEY,
    }
```

- [ ] **Step 5: Mount it as a public router**

In `app/main.py`, beside the `health` include (the public one, no `dependencies=`), add the import with the other router imports and:

```python
app.include_router(
    auth_config.router,
    prefix=f"{settings.API_V1_STR}/auth",
    tags=["auth"],
)
```

(Import: add `auth_config` to the existing `from app.api.routers import (...)` group.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_auth_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd gigaflow
git add backend/app/core/config.py backend/app/api/routers/auth_config.py backend/app/main.py backend/tests/api/test_auth_config.py
git commit -m "feat(backend): public /api/v1/auth/config endpoint for CLI Supabase config"
```

---

### Task A3: Swap customer-API auth gate to identity-aware `get_current_user`

`require_flow_compute_auth` only gates (returns `None`). `get_current_user` gates *and* yields the user identity, accepting the same static key + dev-mode. Swapping the router-wide gate to it loses nothing and lets route functions receive the caller's `user_id` (FastAPI caches the dependency within a request, so re-declaring it as a route param is free).

**Files:**
- Modify: `gigaflow/backend/app/main.py`
- Test: `gigaflow/backend/tests/api/test_customer_auth_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow/backend/tests/api/test_customer_auth_gate.py
"""The customer routers must reject anonymous callers and accept the static key."""
import app.main as main_mod


def test_customer_deps_use_get_current_user():
    # The shared dependency list gating customer routers must be the
    # identity-aware get_current_user (not the gate-only flow auth).
    from app.api.deps.supabase_auth import get_current_user
    dep_callables = [d.dependency for d in main_mod._customer_api_deps]
    assert get_current_user in dep_callables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_customer_auth_gate.py -v`
Expected: FAIL — list still holds `require_flow_compute_auth`.

- [ ] **Step 3: Swap the dependency**

In `app/main.py`, change the import and the shared dep list:

```python
from app.api.deps.supabase_auth import get_current_user
# (keep the require_flow_compute_auth import only if still used elsewhere; remove if not)

_customer_api_deps = [Depends(get_current_user)]
```

Leave every `app.include_router(..., dependencies=_customer_api_deps)` call unchanged — they now gate via `get_current_user`, which still accepts the static `FLOW_COMPUTE_API_KEY` and honors `GIGAFLOW_DEV_MODE`.

- [ ] **Step 4: Run test + full router auth tests to verify nothing regressed**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_customer_auth_gate.py tests/api/test_production_api_auth.py tests/api/test_flow_compute_auth.py -v`
Expected: PASS (static-key and dev-mode paths still authenticate).

- [ ] **Step 5: Commit**

```bash
cd gigaflow
git add backend/app/main.py backend/tests/api/test_customer_auth_gate.py
git commit -m "feat(backend): gate customer routers with identity-aware get_current_user"
```

---

### Task A4: Stamp project owner on create; scope project reads by owner

**Files:**
- Modify: `gigaflow/backend/app/api/routers/projects.py`
- Test: `gigaflow/backend/tests/api/test_project_owner_scoping.py`

- [ ] **Step 1: Write the failing tests**

```python
# gigaflow/backend/tests/api/test_project_owner_scoping.py
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers import projects
from app.api.deps.supabase_auth import get_current_user
from app.db.traces import get_traces_db

USER = UUID("11111111-1111-1111-1111-111111111111")


def _make_app(db, user_id):
    app = FastAPI()
    app.include_router(projects.router, prefix="/api/v1/projects")

    async def _db():
        yield db

    async def _user():
        return user_id

    app.dependency_overrides[get_traces_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return app


async def test_create_project_stamps_owner():
    db = AsyncMock()
    captured = {}

    def _add(obj):
        captured["obj"] = obj
    db.add.side_effect = _add

    async def _refresh(obj):
        obj.project_id = uuid4()
    db.refresh.side_effect = _refresh

    app = _make_app(db, USER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/v1/projects/", json={"name": "p"})
    assert resp.status_code == 200
    assert captured["obj"].user_id == USER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_project_owner_scoping.py -v`
Expected: FAIL — `Project(...)` created without `user_id`.

- [ ] **Step 3: Stamp owner on create + filter list by owner**

In `app/api/routers/projects.py`, import `get_current_user` and `UUID`, then:

`create_project`:

```python
from uuid import UUID
from app.api.deps.supabase_auth import get_current_user


@router.post("/")
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_traces_db),
    user_id: UUID | None = Depends(get_current_user),
):
    """Create a new project, owned by the authenticated user (if any)."""
    project = Project(name=body.name, user_id=user_id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project
```

`list_projects` — add the param and an owner filter on the project query/count. When `user_id` is `None` (service/dev caller) keep the existing unscoped behavior:

```python
@router.get("/")
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_traces_db),
    user_id: UUID | None = Depends(get_current_user),
):
    ...
    # Where the project SELECT and the trace-count subqueries are built, add:
    #   if user_id is not None:
    #       <project_query> = <project_query>.filter(Project.user_id == user_id)
    # Apply the same Project.user_id == user_id filter to any count/aggregate
    # query that joins projects. The "unassigned" bucket (Trace.project_id IS
    # NULL) is service-only data — when user_id is not None, force its count to 0.
```

Also update `get_project` (the `GET /{project_id}` route): add the `user_id` param and, after loading the project, `if user_id is not None and project.user_id != user_id: raise HTTPException(status_code=404, detail="Project not found")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_project_owner_scoping.py tests/api/test_projects.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd gigaflow
git add backend/app/api/routers/projects.py backend/tests/api/test_project_owner_scoping.py
git commit -m "feat(backend): stamp + scope projects by owner user_id"
```

---

### Task A5: Scope trace reads by owner

`Trace.user_id` already exists. Filter the list/detail reads so a Supabase user only sees their own traces; service/dev callers (`user_id is None`) stay unscoped.

**Files:**
- Modify: `gigaflow/backend/app/api/routers/traces.py`
- Test: `gigaflow/backend/tests/api/test_trace_owner_scoping.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow/backend/tests/api/test_trace_owner_scoping.py
from uuid import UUID
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers import traces
from app.api.deps.supabase_auth import get_current_user
from app.db.traces import get_traces_db

USER = UUID("11111111-1111-1111-1111-111111111111")


async def test_list_traces_filters_by_owner_when_user_present():
    db = AsyncMock()
    # Capture the compiled WHERE clause text to assert user_id filtering.
    seen = {}

    async def _execute(stmt):
        seen.setdefault("statements", []).append(str(stmt))
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        return result
    db.execute.side_effect = _execute

    app = FastAPI()
    app.include_router(traces.router, prefix="/api/v1/traces")

    async def _db():
        yield db

    async def _user():
        return USER

    app.dependency_overrides[get_traces_db] = _db
    app.dependency_overrides[get_current_user] = _user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/v1/traces/")
    assert resp.status_code == 200
    assert any("user_id" in s for s in seen["statements"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_trace_owner_scoping.py -v`
Expected: FAIL — no `user_id` in the query.

- [ ] **Step 3: Add owner filtering**

In `app/api/routers/traces.py`, add `from uuid import UUID` (if not present) and `from app.api.deps.supabase_auth import get_current_user`, then add the param and filter to `list_traces`:

```python
@router.get("/")
async def list_traces(
    skip: int = 0,
    limit: int = 100,
    project_id: str | None = None,
    db: AsyncSession = Depends(get_traces_db),
    user_id: UUID | None = Depends(get_current_user),
):
    query = select(Trace)
    count_query = select(func.count()).select_from(Trace)
    if user_id is not None:
        query = query.filter(Trace.user_id == user_id)
        count_query = count_query.filter(Trace.user_id == user_id)
    # ... existing project_id branch unchanged ...
```

For `get_trace`, `get_trace_spans`, `get_trace_source`: add the `user_id` param and, after loading the trace, `if user_id is not None and trace.user_id != user_id: raise HTTPException(status_code=404, detail="Trace not found")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gigaflow/backend && uv run pytest tests/api/test_trace_owner_scoping.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd gigaflow
git add backend/app/api/routers/traces.py backend/tests/api/test_trace_owner_scoping.py
git commit -m "feat(backend): scope trace reads by owner user_id"
```

---

### Task A6: Inherit owner on ingest (OTLP + datasource sync)

So CLI-driven traces actually carry an owner: when a trace is created in an owned project, stamp `Trace.user_id` from the project's owner.

**Files:**
- Create: `gigaflow/backend/app/services/ownership.py`
- Modify: `gigaflow/backend/app/api/routers/otlp.py` (trace-construction site)
- Modify: the datasource-sync trace-creation path (locate via `grep -rn "Trace(" app/` — typically `app/datasources/` or `app/ingest/`)
- Test: `gigaflow/backend/tests/test_ownership_helper.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow/backend/tests/test_ownership_helper.py
from uuid import uuid4
from app.services.ownership import owner_of_project
from app.models.project import Project


def test_owner_of_project_returns_user_id():
    uid = uuid4()
    p = Project(name="x", user_id=uid)
    assert owner_of_project(p) == uid


def test_owner_of_project_none_when_unowned():
    p = Project(name="x")
    assert owner_of_project(p) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow/backend && uv run pytest tests/test_ownership_helper.py -v`
Expected: FAIL — no `ownership` module.

- [ ] **Step 3: Implement the helper**

```python
# gigaflow/backend/app/services/ownership.py
"""Resolve the owning user for ingested traces.

Ownership is project-level (see the per-user CLI accounts spec): a trace
inherits the user_id of the project it lands in. OTLP tokens and datasource
syncs both target a known project, so the owner flows through here.
"""
from uuid import UUID
from app.models.project import Project


def owner_of_project(project: Project) -> UUID | None:
    """The Supabase user that owns ``project`` (or None for service projects)."""
    return getattr(project, "user_id", None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow/backend && uv run pytest tests/test_ownership_helper.py -v`
Expected: PASS.

- [ ] **Step 5: Apply at trace-creation sites**

In `app/api/routers/otlp.py`, where the receiver builds `Trace(...)` after resolving the per-project token's project, set `user_id=owner_of_project(project)`. Do the same at the datasource-sync `Trace(...)` construction (the project is already loaded there). Add `from app.services.ownership import owner_of_project` to each.

- [ ] **Step 6: Write/extend an integration-ish test for the OTLP path**

Add a test mirroring the existing OTLP receiver tests (see `tests/api/test_otlp_*`) that ingests into a project with a `user_id` and asserts the created `Trace.user_id` equals the project owner. Reuse the existing OTLP test fixtures.

Run: `cd gigaflow/backend && uv run pytest tests/api/test_otlp_tokens_router.py tests/test_ownership_helper.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd gigaflow
git add backend/app/services/ownership.py backend/app/api/routers/otlp.py backend/tests/test_ownership_helper.py
git commit -m "feat(backend): inherit project owner on OTLP + sync trace ingest"
```

---

# Phase B — SDK (`gigaflow-sdk`)

Stdlib only — no new dependencies. Reuses the fact that `_http.api()` and `supplement._post_supplement()` already send `api_key` as `Authorization: Bearer`, so once `cli.py` resolves the user's access token into `args.api_key`, every existing upload path is user-scoped with no further change.

### Task B1: Credential store (`_auth.py`)

**Files:**
- Create: `gigaflow/gigaflow/_auth.py`
- Test: `gigaflow/gigaflow-sdk/tests/test_auth_store.py` → actual path `gigaflow-sdk/tests/test_auth_store.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow-sdk/tests/test_auth_store.py
import json
import os
import stat
from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-sdk && uv run pytest tests/test_auth_store.py -v`
Expected: FAIL — no `_auth` module.

- [ ] **Step 3: Implement the store**

```python
# gigaflow-sdk/gigaflow/_auth.py
"""Per-user Supabase credentials for the CLI.

Stored separately from config.json in ~/.gigaflow/credentials.json (mode 0600).
Holds the Supabase session (access + refresh tokens) obtained via `gigaflow
login`. Token values are never logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow-sdk && uv run pytest tests/test_auth_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd gigaflow-sdk
git add gigaflow/_auth.py tests/test_auth_store.py
git commit -m "feat(sdk): credentials store at ~/.gigaflow/credentials.json (0600)"
```

---

### Task B2: Token refresh + `access_token()` resolver

**Files:**
- Modify: `gigaflow/gigaflow-sdk/gigaflow/_auth.py` → `gigaflow-sdk/gigaflow/_auth.py`
- Test: `gigaflow-sdk/tests/test_auth_refresh.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow-sdk/tests/test_auth_refresh.py
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
    # Rotated tokens are persisted.
    assert _auth.load_credentials()["access_token"] == "fresh"


def test_access_token_none_when_logged_out(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "none.json")
    assert _auth.access_token("http://backend/api/v1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-sdk && uv run pytest tests/test_auth_refresh.py -v`
Expected: FAIL — `access_token` / helpers undefined.

- [ ] **Step 3: Implement refresh + resolver**

Append to `gigaflow/_auth.py`:

```python
import time
import urllib.request
import urllib.error

from gigaflow._http import api

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow-sdk && uv run pytest tests/test_auth_refresh.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd gigaflow-sdk
git add gigaflow/_auth.py tests/test_auth_refresh.py
git commit -m "feat(sdk): Supabase token refresh + access_token() resolver"
```

---

### Task B3: Loopback login + `login`/`logout`/`whoami` commands

**Files:**
- Modify: `gigaflow-sdk/gigaflow/_auth.py` (add `run_loopback_login`)
- Create: `gigaflow-sdk/gigaflow/commands/auth.py`
- Test: `gigaflow-sdk/tests/test_auth_login.py`

- [ ] **Step 1: Write the failing test for the loopback handshake**

```python
# gigaflow-sdk/tests/test_auth_login.py
import threading
import urllib.request

import gigaflow._auth as _auth


def test_loopback_login_captures_matching_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")
    monkeypatch.setattr(_auth, "_now", lambda: 1000)

    opened = {}

    def fake_open(url):
        opened["url"] = url
        # Simulate the browser/page redirecting to the loopback callback.
        # Parse the port + state the CLI advertised, then hit the callback.
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        port, state = q["port"][0], q["state"][0]
        cb = (f"http://127.0.0.1:{port}/callback?state={state}"
              f"&access_token=AT&refresh_token=RT&expires_in=3600&email=u%40x.com")
        threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5)).start()

    monkeypatch.setattr(_auth.webbrowser, "open", fake_open)

    creds = _auth.run_loopback_login("https://api.gigaflow.io", timeout=5)
    assert creds["access_token"] == "AT"
    assert creds["email"] == "u@x.com"
    assert creds["expires_at"] == 1000 + 3600
    assert "/cli-auth?" in opened["url"]
    # Persisted.
    assert _auth.load_credentials()["refresh_token"] == "RT"


def test_loopback_login_rejects_bad_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_auth, "CREDENTIALS_PATH", tmp_path / "c.json")

    def fake_open(url):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        port = q["port"][0]
        cb = (f"http://127.0.0.1:{port}/callback?state=WRONG"
              f"&access_token=AT&refresh_token=RT&expires_in=3600&email=u%40x.com")
        threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5)).start()

    monkeypatch.setattr(_auth.webbrowser, "open", fake_open)
    creds = _auth.run_loopback_login("https://api.gigaflow.io", timeout=5)
    assert creds is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-sdk && uv run pytest tests/test_auth_login.py -v`
Expected: FAIL — `run_loopback_login` undefined.

- [ ] **Step 3: Implement the loopback login**

Append to `gigaflow/_auth.py`:

```python
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs


def _web_base(api_base_url: str) -> str:
    """Derive the website origin from the API base URL.

    The website (api.gigaflow.io) and API (api.gigaflow.io/api/v1) share a host,
    so stripping the /api/v1 suffix yields the site origin.
    """
    return api_base_url.replace("/api/v1", "").rstrip("/")


def run_loopback_login(api_base_url: str, timeout: int = 120) -> dict | None:
    """Browser loopback login. Returns the saved credentials dict, or None.

    1. Bind a one-shot http server on 127.0.0.1:<random port>.
    2. Open the browser to <site>/cli-auth?port=&state=.
    3. The page redirects the Supabase session back to /callback; we verify the
       state nonce, persist the tokens, and show a success page.
    """
    state = secrets.token_urlsafe(24)
    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = parse_qs(urlparse(self.path).query)
            got_state = (params.get("state") or [None])[0]
            if got_state != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"state mismatch")
                return
            captured.update({
                "access_token": (params.get("access_token") or [None])[0],
                "refresh_token": (params.get("refresh_token") or [None])[0],
                "expires_at": _now() + int((params.get("expires_in") or ["3600"])[0]),
                "email": (params.get("email") or [None])[0],
            })
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Signed in. You can close this tab and return to your terminal.</h2>")

        def log_message(self, *args):  # silence default stderr logging
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = timeout
    port = server.server_address[1]
    url = f"{_web_base(api_base_url)}/cli-auth?port={port}&state={state}"
    print(f"  Opening {url}")
    print("  If your browser didn't open, paste that URL into it.")
    webbrowser.open(url)
    server.handle_request()  # serves exactly one request (or times out)
    server.server_close()

    if not captured.get("access_token") or (captured.get("state") not in (None, state) and not captured):
        return None
    if not captured.get("access_token"):
        return None

    # Cache the Supabase config for later refreshes.
    supabase_url, anon_key = _fetch_auth_config(api_base_url)
    creds = {**captured, "supabase_url": supabase_url, "anon_key": anon_key}
    save_credentials(creds)
    return creds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow-sdk && uv run pytest tests/test_auth_login.py -v`
Expected: PASS (both the matching-state and bad-state cases).

- [ ] **Step 5: Implement the commands module**

```python
# gigaflow-sdk/gigaflow/commands/auth.py
"""login / logout / whoami — per-user Supabase identity for the CLI."""
from gigaflow import _auth, _fmt


def register(sub) -> None:
    sub.add_parser("login", help="Sign in via the browser and store credentials").set_defaults(func=_handle_login)
    sub.add_parser("logout", help="Clear stored credentials").set_defaults(func=_handle_logout)
    sub.add_parser("whoami", help="Show the signed-in account").set_defaults(func=_handle_whoami)


def _handle_login(args, base_url: str) -> None:
    _fmt.header("GigaFlow Login")
    creds = _auth.run_loopback_login(base_url)
    if not creds:
        _fmt.fail("Login was not completed.")
        _fmt.info("Sign up or sign in at https://api.gigaflow.io, then run: gigaflow login")
        return
    _fmt.ok(f"Signed in as {creds.get('email', 'your account')}")


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

- [ ] **Step 6: Commit**

```bash
cd gigaflow-sdk
git add gigaflow/_auth.py gigaflow/commands/auth.py tests/test_auth_login.py
git commit -m "feat(sdk): browser loopback login + login/logout/whoami commands"
```

---

### Task B4: Register `auth` commands + credential precedence in `cli.py`

**Files:**
- Modify: `gigaflow-sdk/gigaflow/cli.py`
- Test: `gigaflow-sdk/tests/test_cli_credential_precedence.py`

- [ ] **Step 1: Write the failing test**

```python
# gigaflow-sdk/tests/test_cli_credential_precedence.py
"""The resolved bearer credential prefers the user token over the static key."""
import gigaflow.cli as cli


def test_user_token_preferred_over_config_key(monkeypatch):
    monkeypatch.setattr(cli._auth, "access_token", lambda base: "USER_JWT")
    resolved = cli._resolve_credential(
        flag=None, env_key=None, user_token="USER_JWT", config_key="STATIC"
    )
    assert resolved == "USER_JWT"


def test_explicit_flag_wins(monkeypatch):
    resolved = cli._resolve_credential(
        flag="FLAG", env_key="ENV", user_token="USER_JWT", config_key="STATIC"
    )
    assert resolved == "FLAG"


def test_falls_back_to_static_when_logged_out():
    resolved = cli._resolve_credential(
        flag=None, env_key=None, user_token=None, config_key="STATIC"
    )
    assert resolved == "STATIC"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-sdk && uv run pytest tests/test_cli_credential_precedence.py -v`
Expected: FAIL — `_resolve_credential` / `cli._auth` undefined.

- [ ] **Step 3: Wire it into `cli.py`**

Add the import near the top of `gigaflow/cli.py`:

```python
from gigaflow import _auth
from gigaflow.commands import auth as auth_cmd
```

Register the commands alongside the others (in the block that calls `setup.register(sub)` etc.):

```python
    auth_cmd.register(sub)
```

Add the pure precedence helper (easy to unit-test):

```python
def _resolve_credential(flag, env_key, user_token, config_key):
    """Bearer credential precedence: explicit flag > env static > user token > config key.

    The user token (a Supabase JWT from `gigaflow login`) is preferred over the
    saved static config key, but an explicitly supplied --api-key / env key still
    wins so self-host/CI overrides keep working.
    """
    return flag or env_key or user_token or config_key or None
```

Replace the existing `args.api_key = (...)` resolution block with a call that injects the user token (resolved against the already-computed `base_url`):

```python
    user_token = _auth.access_token(base_url)
    args.api_key = _resolve_credential(
        flag=args.api_key,
        env_key=os.environ.get("GIGAFLOW_API_KEY") or os.environ.get("GIGAFLOW_FLOW_API_KEY"),
        user_token=user_token,
        config_key=cfg.get("api_key"),
    )
```

Add a first-run hint just before dispatch (`args.func(args, base_url)`): if the
command is one of the backend-touching ones and there's no credential at all,
nudge the user. Keep it non-fatal:

```python
    _BACKEND_CMDS = {"traces", "spans", "supplement", "sync", "query", "projects", "compute", "ui"}
    if args.api_key is None and getattr(args, "command", None) in _BACKEND_CMDS:
        _fmt.info("You're not signed in. Run: gigaflow login  (opens api.gigaflow.io)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gigaflow-sdk && uv run pytest tests/test_cli_credential_precedence.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full SDK suite to confirm no regressions**

Run: `cd gigaflow-sdk && uv run pytest -q`
Expected: PASS (existing command/http tests unaffected; logged-out runs fall back to the static key exactly as before).

- [ ] **Step 6: Commit**

```bash
cd gigaflow-sdk
git add gigaflow/cli.py tests/test_cli_credential_precedence.py
git commit -m "feat(sdk): register auth commands + prefer user token over static key"
```

---

# Phase C — Website (`gigaflow-website`)

### Task C1: Add email+password methods to `AuthContext`

**Files:**
- Modify: `gigaflow-website/src/contexts/AuthContext.tsx`
- Test: `gigaflow-website/src/contexts/AuthContext.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// gigaflow-website/src/contexts/AuthContext.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const signInWithPassword = vi.fn(async () => ({ error: null }));
const signUp = vi.fn(async () => ({ error: null }));
vi.mock("../lib/supabase", () => ({
  getSupabase: () => ({
    auth: {
      signInWithPassword,
      signUp,
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  }),
  isSupabaseConfigured: true,
}));

import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { signInWithPassword: sip, signUp: su } = useAuth();
  return (
    <>
      <button onClick={() => sip("u@x.com", "pw")}>signin</button>
      <button onClick={() => su("u@x.com", "pw")}>signup</button>
    </>
  );
}

describe("AuthContext password auth", () => {
  it("calls supabase signInWithPassword", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await userEvent.click(screen.getByText("signin"));
    await waitFor(() =>
      expect(signInWithPassword).toHaveBeenCalledWith({ email: "u@x.com", password: "pw" }));
  });

  it("calls supabase signUp", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await userEvent.click(screen.getByText("signup"));
    await waitFor(() =>
      expect(signUp).toHaveBeenCalledWith({ email: "u@x.com", password: "pw" }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-website && npm run test -- AuthContext`
Expected: FAIL — `signInWithPassword`/`signUp` not on the context value.

- [ ] **Step 3: Extend the context**

In `src/contexts/AuthContext.tsx`, add to `AuthContextValue`:

```tsx
  /** Sign in with email + password. Throws on failure. */
  signInWithPassword: (email: string, password: string) => Promise<void>;
  /** Create an account with email + password. Throws on failure. */
  signUp: (email: string, password: string) => Promise<void>;
```

Implement inside `AuthProvider` (mirroring the existing `signInWithOtp` shape) and add both to the provider `value`:

```tsx
  const signInWithPassword = async (email: string, password: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
  };

  const signUp = async (email: string, password: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) throw error;
  };
```

Keep `signInWithOtp` for now (non-breaking).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow-website && npm run test -- AuthContext`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd gigaflow-website
git add src/contexts/AuthContext.tsx src/contexts/AuthContext.test.tsx
git commit -m "feat(web): add email+password signInWithPassword/signUp to AuthContext"
```

---

### Task C2: `CliAuth` handoff page

Reads `port` + `state` from the query, ensures a Supabase session (email+password form, with a sign-up toggle), then **top-level-redirects** the session to the CLI's loopback callback. Top-level navigation to `http://127.0.0.1:<port>` is not subject to mixed-content/Private-Network-Access blocking (unlike a `fetch`), and avoids Supabase redirect-allowlist constraints since the page — not Supabase — performs the redirect.

**Files:**
- Create: `gigaflow-website/src/components/CliAuth.tsx`
- Test: `gigaflow-website/src/components/CliAuth.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// gigaflow-website/src/components/CliAuth.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const getSession = vi.fn();
vi.mock("../lib/supabase", () => ({
  getSupabase: () => ({ auth: { getSession } }),
  isSupabaseConfigured: true,
}));

import CliAuth from "./CliAuth";

describe("CliAuth handoff", () => {
  beforeEach(() => {
    getSession.mockReset();
    window.history.replaceState({}, "", "/cli-auth?port=54321&state=abc");
  });

  it("redirects the session to the loopback callback with state echoed", async () => {
    getSession.mockResolvedValue({
      data: { session: {
        access_token: "AT", refresh_token: "RT", expires_in: 3600,
        user: { email: "u@x.com" },
      } },
    });
    const assign = vi.fn();
    // jsdom: stub the navigation sink.
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign, search: "?port=54321&state=abc" },
      writable: true,
    });

    render(<CliAuth />);
    await waitFor(() => expect(assign).toHaveBeenCalled());
    const target = assign.mock.calls[0][0] as string;
    expect(target).toContain("http://127.0.0.1:54321/callback");
    expect(target).toContain("state=abc");
    expect(target).toContain("access_token=AT");
    expect(target).toContain("email=u%40x.com");
  });

  it("shows the sign-in form when there's no session", async () => {
    getSession.mockResolvedValue({ data: { session: null } });
    render(<CliAuth />);
    await waitFor(() => expect(screen.getByLabelText(/email/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-website && npm run test -- CliAuth`
Expected: FAIL — no `CliAuth` component.

- [ ] **Step 3: Implement the page**

```tsx
// gigaflow-website/src/components/CliAuth.tsx
import { useEffect, useState } from "react";
import { getSupabase } from "../lib/supabase";
import { useAuth } from "../contexts/AuthContext";

/** Build the loopback callback URL carrying the Supabase session. */
function callbackUrl(port: string, state: string, session: {
  access_token: string; refresh_token: string; expires_in: number;
  user: { email?: string };
}): string {
  const q = new URLSearchParams({
    state,
    access_token: session.access_token,
    refresh_token: session.refresh_token,
    expires_in: String(session.expires_in ?? 3600),
    email: session.user?.email ?? "",
  });
  return `http://127.0.0.1:${port}/callback?${q.toString()}`;
}

export default function CliAuth() {
  const params = new URLSearchParams(window.location.search);
  const port = params.get("port") ?? "";
  const state = params.get("state") ?? "";
  const { signInWithPassword, signUp } = useAuth();

  const [needsLogin, setNeedsLogin] = useState<boolean | null>(null);
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [handedOff, setHandedOff] = useState(false);

  // Once a session exists, hand it off to the CLI's loopback server.
  const handoff = async () => {
    const { data } = await getSupabase().auth.getSession();
    const session = data.session as
      | { access_token: string; refresh_token: string; expires_in: number; user: { email?: string } }
      | null;
    if (!session) { setNeedsLogin(true); return; }
    setHandedOff(true);
    window.location.assign(callbackUrl(port, state, session));
  };

  useEffect(() => { handoff(); /* eslint-disable-next-line */ }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      if (mode === "signin") await signInWithPassword(email, password);
      else await signUp(email, password);
      await handoff();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    }
  };

  if (handedOff) {
    return <main style={{ padding: 32 }}><h2>Signed in. Return to your terminal — you can close this tab.</h2></main>;
  }
  if (needsLogin === null) {
    return <main style={{ padding: 32 }}><p>Connecting…</p></main>;
  }
  return (
    <main style={{ padding: 32, maxWidth: 360 }}>
      <h2>{mode === "signin" ? "Sign in to the GigaFlow CLI" : "Create your GigaFlow account"}</h2>
      <form onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p role="alert">{error}</p>}
        <button type="submit">{mode === "signin" ? "Sign in" : "Sign up"}</button>
      </form>
      <button type="button" onClick={() => setMode(mode === "signin" ? "signup" : "signin")}>
        {mode === "signin" ? "Need an account? Sign up" : "Have an account? Sign in"}
      </button>
    </main>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow-website && npm run test -- CliAuth`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd gigaflow-website
git add src/components/CliAuth.tsx src/components/CliAuth.test.tsx
git commit -m "feat(web): /cli-auth handoff page redirects Supabase session to CLI loopback"
```

---

### Task C3: Render `CliAuth` at `/cli-auth`

The app has no router; switch on `window.location.pathname` at the top of `App` so a real navigation to `/cli-auth` renders the handoff page instead of the marketing site.

**Files:**
- Modify: `gigaflow-website/src/App.tsx`
- Test: `gigaflow-website/src/App.cliauth.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// gigaflow-website/src/App.cliauth.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./components/CliAuth", () => ({ default: () => <div>CLI AUTH PAGE</div> }));

import App from "./App";

describe("App routing for /cli-auth", () => {
  it("renders CliAuth when the path is /cli-auth", () => {
    window.history.replaceState({}, "", "/cli-auth?port=1&state=2");
    render(<App />);
    expect(screen.getByText("CLI AUTH PAGE")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gigaflow-website && npm run test -- App.cliauth`
Expected: FAIL — App renders the marketing site, not CliAuth.

- [ ] **Step 3: Add the path switch**

In `src/App.tsx`, import `CliAuth` and short-circuit at the top of the `App` component (before the providers/marketing tree). Keep providers if `CliAuth` needs `useAuth` — wrap just `CliAuth` in the existing `AuthProvider`:

```tsx
import CliAuth from "./components/CliAuth";

export default function App() {
  if (typeof window !== "undefined" && window.location.pathname === "/cli-auth") {
    return (
      <AuthProvider>
        <CliAuth />
      </AuthProvider>
    );
  }
  // ... existing app tree unchanged ...
}
```

(If `AuthProvider` is applied higher up already, render `<CliAuth />` within that existing provider scope instead of double-wrapping.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gigaflow-website && npm run test -- App.cliauth`
Expected: PASS.

- [ ] **Step 5: Run lint + full web test suite**

Run: `cd gigaflow-website && npm run test && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd gigaflow-website
git add src/App.tsx src/App.cliauth.test.tsx
git commit -m "feat(web): route /cli-auth to the CLI handoff page"
```

---

# Phase D — Config & manual verification (no code)

These are operational steps; record completion in the PR description.

- [ ] **D1 — Supabase dashboard:** Enable the Email provider with **email+password** and **email confirmation** on. (Magic-link can stay enabled; it's additive.)
- [ ] **D2 — Backend env:** Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` (and confirm the existing `SUPABASE_JWKS_URL` / `SUPABASE_JWT_*` are set so JWT verification works). Redeploy.
- [ ] **D3 — Hosting SPA fallback:** Ensure the static host serves `index.html` for `GET /cli-auth` (so the deep link loads the SPA). For Vite preview/dev this already works; for the production host (CloudFront/S3/nginx) add the SPA fallback rule for `/cli-auth`.
- [ ] **D4 — End-to-end smoke test:**
  1. `cd gigaflow-sdk && uv run gigaflow login` → browser opens `/cli-auth` → sign up → tab shows success → terminal prints `Signed in as <email>`.
  2. `uv run gigaflow whoami` → shows the email.
  3. Upload a trace (`uv run gigaflow supplement --latest`) → succeeds.
  4. Open api.gigaflow.io, sign in with the same account → the uploaded trace appears; a second account sees none of it.

---

## Self-Review

**Spec coverage:**
- Credential store `~/.gigaflow/credentials.json` (0600) → **B1.** ✅
- `gigaflow login` browser loopback handoff → **B3** (server) + **C2/C3** (page) ✅
- `logout` / `whoami` → **B3.** ✅
- First-run gate / hint → **B4.** ✅
- Token refresh + 401 handling → **B2** (refresh) — note: the explicit 401-retry-once in `_http.api()` is *not* a separate task; refresh-before-expiry (B2) covers the common case, and a stale token surfaces the existing auth-error hint. **Added scope note below.**
- Credential precedence → **B4.** ✅
- `auth/config` endpoint → **A2.** ✅
- `Project.user_id` + migration → **A1.** ✅
- Identity-aware gate swap → **A3.** ✅
- Write scoping (owner stamp + ingest inheritance) → **A4 + A6.** ✅
- Read scoping (projects + traces) → **A4 + A5.** ✅
- Website password methods + `/cli-auth` page + route → **C1/C2/C3.** ✅
- Supabase config / env / SPA fallback → **D1–D3.** ✅

**Scope note (explicit, intentional):** The spec mentions a 401→refresh→retry in `_http.api()`. This plan implements proactive refresh (B2, refresh when within 60s of expiry) which covers the realistic case without threading refresh logic through the stdlib HTTP retry loop. A reactive 401-retry can be added later if proactive refresh proves insufficient; it is deliberately deferred to keep `_http.py` simple. Flagged here so it isn't mistaken for a gap.

**Placeholder scan:** One deliberate non-literal — A6 says "locate the datasource-sync `Trace(...)` site via grep" because that construction site isn't pinned to an exact line in this repo snapshot; the grep command is given. All other steps contain literal code.

**Type/name consistency:** `access_token(base_url)`, `load_credentials`/`save_credentials`/`clear_credentials`, `run_loopback_login(api_base_url, timeout)`, `_resolve_credential(flag, env_key, user_token, config_key)`, `owner_of_project(project)`, `CREDENTIALS_PATH`, and the `{access_token, refresh_token, expires_at, email, supabase_url, anon_key}` credential shape are used consistently across B1–B4 and the website's `expires_in`→`expires_at` conversion. Backend `user_id: UUID | None = Depends(get_current_user)` param is used identically in A4/A5.
