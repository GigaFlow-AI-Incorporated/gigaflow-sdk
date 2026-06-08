# Admin Allowlist Page (shared-token) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator a protected `/admin` page on gigaflow.io to list/add/remove allowlisted emails (no SQL, no customer CLI), backed by an admin-token-gated backend API.

**Architecture:** Two phases. **Backend (`gigaflow`)** adds a `GIGAFLOW_ADMIN_TOKEN` setting, a `require_admin` dependency (mirrors `flow_auth.require_flow_compute_auth`: Bearer token, constant-time compare, 503 fail-closed when unset, dev-mode bypass), and a `/api/v1/admin/allowlist` router (GET/POST/DELETE) reusing the existing `AllowlistedEmail` model. **Website (`gigaflow-website`)** adds a same-origin Cloudflare Pages Function proxy (`functions/api/admin/[[path]].ts`, mirrors `analyze.ts`) that forwards the operator's bearer token to the backend, plus an `/admin` page (`AdminAllowlist.tsx`) that stores the token in `localStorage` and calls the proxy.

**Tech Stack:** FastAPI + SQLAlchemy async + PyJWT (backend); Cloudflare Pages Functions (TS) + Vite/React/TS + Vitest (website). Backend tests: pytest. Website tests: vitest (jsdom).

**Spec:** `docs/superpowers/specs/2026-06-08-admin-allowlist-page-design.md` (reuses the `allowlisted_emails` table from the email-only waitlist feature).

**Spec refinement (decided during planning):** transport is a **same-origin Pages Function proxy** (`/api/admin/*` → `GIGAFLOW_BACKEND_URL/api/v1/admin/*`), matching `functions/api/analyze.ts`, instead of the browser calling `api.gigaflow.io` directly. Same token model (operator enters the token; the browser sends it as `Authorization: Bearer`; the function forwards it). Keeps the backend origin hidden and avoids relying on CORS.

**Repo paths:**
- Backend: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow` (worktree: `.claude/worktrees/admin-allowlist`, branch `feat/admin-allowlist`)
- Website: `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-website` (worktree created at Phase 2)

**Per-repo branches / PRs (merge in order):**
1. backend → `feat/admin-allowlist` → PR, **merge first**, then set `GIGAFLOW_ADMIN_TOKEN` in prod env.
2. website → `feat/admin-allowlist-page` → PR.

**Env:** backend needs `GIGAFLOW_ADMIN_TOKEN` (delivered out of band). Website reuses the existing `GIGAFLOW_BACKEND_URL` Pages env var (already set for `analyze.ts`).

---

## Phase 1 — Backend (`gigaflow`)

Work in worktree `/Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow/.claude/worktrees/admin-allowlist` (branch `feat/admin-allowlist`, off origin/main).

**Test runner (fresh-worktree uv split — use this exact form):**
`cd backend && uv run --extra dev --package gigaflow-backend python -m pytest <path> -v`
**Lint:** `cd backend && uv run --extra dev --package gigaflow-backend ruff check <path>`

### Task 1: `GIGAFLOW_ADMIN_TOKEN` setting

**Files:**
- Modify: `backend/app/core/config.py` (add the setting next to `FLOW_COMPUTE_API_KEY`, ~line 118)

- [ ] **Step 1: Add the setting**

In `backend/app/core/config.py`, immediately after the `FLOW_COMPUTE_API_KEY: str | None = None` line, add:

```python
    # Shared secret gating the internal admin API (/api/v1/admin/*). Fail-closed:
    # unset in prod -> admin endpoints return 503; GIGAFLOW_DEV_MODE bypasses it.
    GIGAFLOW_ADMIN_TOKEN: str | None = None
```

- [ ] **Step 2: Verify it loads**

Run: `cd backend && uv run --extra dev --package gigaflow-backend python -c "from app.core.config import settings; print(repr(settings.GIGAFLOW_ADMIN_TOKEN))"`
Expected: prints `None` (unset by default).

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/config.py
git commit -m "feat(backend): add GIGAFLOW_ADMIN_TOKEN setting"
```

### Task 2: `require_admin` dependency

**Files:**
- Create: `backend/app/api/deps/admin_auth.py`
- Test: `backend/tests/api/deps/test_admin_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/deps/test_admin_auth.py
"""require_admin: shared-token gate (mirrors flow_auth)."""
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps.admin_auth import require_admin
from app.core.config import settings


def _client():
    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(require_admin)])
    async def guarded():
        return {"ok": True}

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(settings, "GIGAFLOW_DEV_MODE", False)
    monkeypatch.setattr(settings, "GIGAFLOW_ADMIN_TOKEN", "secret-admin-token")


@pytest.mark.asyncio
async def test_valid_token_passes():
    async with _client() as c:
        resp = await c.get("/guarded", headers={"Authorization": "Bearer secret-admin-token"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_header_401():
    async with _client() as c:
        resp = await c.get("/guarded")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_401():
    async with _client() as c:
        resp = await c.get("/guarded", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unset_token_503(monkeypatch):
    monkeypatch.setattr(settings, "GIGAFLOW_ADMIN_TOKEN", None)
    async with _client() as c:
        resp = await c.get("/guarded", headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_dev_mode_bypasses(monkeypatch):
    monkeypatch.setattr(settings, "GIGAFLOW_DEV_MODE", True)
    monkeypatch.setattr(settings, "GIGAFLOW_ADMIN_TOKEN", None)
    async with _client() as c:
        resp = await c.get("/guarded")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --extra dev --package gigaflow-backend python -m pytest tests/api/deps/test_admin_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.deps.admin_auth'`

- [ ] **Step 3: Write the dependency**

```python
# backend/app/api/deps/admin_auth.py
"""Admin API gate — a single shared token (GIGAFLOW_ADMIN_TOKEN).

Mirrors flow_auth.require_flow_compute_auth: Bearer token, constant-time compare,
fail-closed (503) when unset in prod, dev-mode bypass. Gates the /api/v1/admin
allowlist-management endpoints, which are mounted outside the customer-auth gate.
This module never logs the token.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings

_BEARER_PREFIX = "Bearer "


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def require_admin(authorization: str | None = Header(default=None)) -> None:
    """Reject unless the caller presents the shared admin token.

    1. GIGAFLOW_DEV_MODE -> allow (local-dev escape).
    2. GIGAFLOW_ADMIN_TOKEN unset -> 503 (fail-closed).
    3. Header missing / not Bearer -> 401.
    4. Token mismatch -> 401.
    """
    if settings.GIGAFLOW_DEV_MODE:
        return None
    expected = settings.GIGAFLOW_ADMIN_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin API is not configured. Set GIGAFLOW_ADMIN_TOKEN in the "
                "backend env, or set GIGAFLOW_DEV_MODE=true for local development."
            ),
        )
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header (expected 'Bearer <token>').",
        )
    presented = authorization[len(_BEARER_PREFIX):].strip()
    if not _constant_time_eq(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --extra dev --package gigaflow-backend python -m pytest tests/api/deps/test_admin_auth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps/admin_auth.py backend/tests/api/deps/test_admin_auth.py
git commit -m "feat(backend): require_admin shared-token dependency"
```

### Task 3: Admin allowlist router + mount

**Files:**
- Create: `backend/app/api/routers/admin.py`
- Modify: `backend/app/main.py` (import `admin` + `require_admin`; mount the router)
- Test: `backend/tests/api/test_admin_allowlist.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_admin_allowlist.py
"""Admin allowlist endpoints (app/api/routers/admin.py). DB mocked via AsyncMock."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers import admin
from app.core.config import settings
from app.db.traces import get_traces_db

BASE = settings.API_V1_STR


def _make_client(db):
    app = FastAPI()
    app.include_router(admin.router, prefix=f"{BASE}/admin")

    async def _override_db():
        yield db

    app.dependency_overrides[get_traces_db] = _override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _base_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_returns_rows():
    row = MagicMock()
    row.email = "a@x.com"
    row.added_at = datetime.now(tz=UTC)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db = _base_db()
    db.execute = AsyncMock(return_value=result)
    async with _make_client(db) as c:
        resp = await c.get(f"{BASE}/admin/allowlist")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["emails"][0]["email"] == "a@x.com"
    assert body["emails"][0]["added_at"] is not None


@pytest.mark.asyncio
async def test_add_inserts_and_reports_added():
    result = MagicMock()
    result.rowcount = 1
    db = _base_db()
    db.execute = AsyncMock(return_value=result)
    async with _make_client(db) as c:
        resp = await c.post(f"{BASE}/admin/allowlist", json={"email": "new@x.com"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"email": "new@x.com", "added": True}
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_add_conflict_reports_not_added():
    result = MagicMock()
    result.rowcount = 0
    db = _base_db()
    db.execute = AsyncMock(return_value=result)
    async with _make_client(db) as c:
        resp = await c.post(f"{BASE}/admin/allowlist", json={"email": "dup@x.com"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"email": "dup@x.com", "added": False}


@pytest.mark.asyncio
async def test_add_invalid_email_422():
    db = _base_db()
    async with _make_client(db) as c:
        resp = await c.post(f"{BASE}/admin/allowlist", json={"email": "not-an-email"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_removes():
    result = MagicMock()
    result.rowcount = 1
    db = _base_db()
    db.execute = AsyncMock(return_value=result)
    async with _make_client(db) as c:
        resp = await c.delete(f"{BASE}/admin/allowlist/gone@x.com")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"email": "gone@x.com", "removed": True}
    db.commit.assert_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --extra dev --package gigaflow-backend python -m pytest tests/api/test_admin_allowlist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.routers.admin'`

- [ ] **Step 3: Write the router**

```python
# backend/app/api/routers/admin.py
"""Admin allowlist management (/api/v1/admin/allowlist).

Gated by require_admin (shared GIGAFLOW_ADMIN_TOKEN), mounted OUTSIDE the
customer-auth gate. Lets the operator list/add/remove allowlisted emails without
raw SQL. Reuses the AllowlistedEmail model.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.traces import get_traces_db
from app.models.allowlist import AllowlistedEmail

router = APIRouter()


class AddEmailRequest(BaseModel):
    email: EmailStr


@router.get("/allowlist")
async def list_allowlist(db: AsyncSession = Depends(get_traces_db)) -> dict:
    rows = (
        await db.execute(
            select(AllowlistedEmail).order_by(AllowlistedEmail.added_at)
        )
    ).scalars().all()
    return {
        "emails": [
            {
                "email": str(r.email),
                "added_at": r.added_at.isoformat() if r.added_at else None,
            }
            for r in rows
        ]
    }


@router.post("/allowlist")
async def add_allowlist(
    body: AddEmailRequest, db: AsyncSession = Depends(get_traces_db)
) -> dict:
    email = body.email.strip()
    stmt = (
        pg_insert(AllowlistedEmail)
        .values(email=email)
        .on_conflict_do_nothing(index_elements=["email"])
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"email": email, "added": (result.rowcount or 0) > 0}


@router.delete("/allowlist/{email}")
async def remove_allowlist(
    email: str, db: AsyncSession = Depends(get_traces_db)
) -> dict:
    result = await db.execute(
        delete(AllowlistedEmail).where(AllowlistedEmail.email == email)
    )
    await db.commit()
    return {"email": email, "removed": (result.rowcount or 0) > 0}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --extra dev --package gigaflow-backend python -m pytest tests/api/test_admin_allowlist.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Mount the router in `main.py`**

In `backend/app/main.py`:

(a) Add `admin` to the routers import tuple (the `from app.api.routers import (...)` block — add `admin,` alphabetically first):

```python
    admin,
    auth,
    auth_config,
```

(b) Add the `require_admin` import next to the other deps imports (near `from app.api.deps.user_auth import require_authenticated`):

```python
from app.api.deps.admin_auth import require_admin
```

(c) Mount the router right after the `auth_config` router include (so all `/auth/*` includes stay together, then admin):

```python
# Internal admin API — GET/POST/DELETE /api/v1/admin/allowlist. Mounted OUTSIDE
# the customer-auth gate; gated by its own shared-token dependency.
app.include_router(
    admin.router,
    prefix=f"{settings.API_V1_STR}/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)
```

(`Depends` is already imported in `main.py`.)

- [ ] **Step 6: Verify the app imports and the full auth+admin suite passes**

Run: `cd backend && uv run --extra dev --package gigaflow-backend python -m pytest tests/api/test_admin_allowlist.py tests/api/deps/test_admin_auth.py tests/api/test_auth_endpoints.py -q`
Expected: PASS (all). Then confirm the app wires up:
`cd backend && uv run --extra dev --package gigaflow-backend python -c "from app.main import app; print('routes:', any(r.path == '/api/v1/admin/allowlist' for r in app.routes))"`
Expected: `routes: True`

- [ ] **Step 7: Lint**

Run: `cd backend && uv run --extra dev --package gigaflow-backend ruff check app/api/routers/admin.py app/api/deps/admin_auth.py app/main.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routers/admin.py backend/app/main.py backend/tests/api/test_admin_allowlist.py
git commit -m "feat(backend): /api/v1/admin/allowlist list/add/remove endpoints"
```

---

## Phase 2 — Website (`gigaflow-website`)

Work in a worktree on branch `feat/admin-allowlist-page` (off origin/main). `node_modules` will be symlinked from the main checkout — **do NOT run `npm install`**.

**Test runner:** `npm run test -- <file>` (vitest). **Build:** `npm run build`.

### Task 4: Cloudflare Pages Function proxy

**Files:**
- Create: `functions/api/admin/[[path]].ts`

> Mirrors `functions/api/analyze.ts`. No vitest test (Pages Functions aren't unit-tested in this repo — `functions/api/*.test.ts` only cover `validation.ts`). Verified via `npm run build` + the Phase-2 manual check.

- [ ] **Step 1: Write the proxy**

```typescript
// functions/api/admin/[[path]].ts
interface Env {
  GIGAFLOW_BACKEND_URL: string;
}

// Same-origin proxy for the internal admin allowlist API. The browser calls
// /api/admin/* (no CORS); we forward to the AWS backend with the operator's
// admin token (Authorization: Bearer <token>) attached verbatim. Mirrors
// functions/api/analyze.ts. The backend's require_admin verifies the token.
export const onRequest: PagesFunction<Env> = async ({ request, env, params }) => {
  if (!env.GIGAFLOW_BACKEND_URL) {
    return json({ error: "server not configured" }, 500);
  }
  const auth = request.headers.get("Authorization");
  if (!auth) return json({ error: "missing authorization" }, 401);

  const raw = params.path;
  const segments = Array.isArray(raw) ? raw : raw ? [raw] : [];
  const subpath = segments.map(encodeURIComponent).join("/");
  const search = new URL(request.url).search;
  const base = env.GIGAFLOW_BACKEND_URL.replace(/\/$/, "");
  const upstream = `${base}/api/v1/admin/${subpath}${search}`;

  const headers: Record<string, string> = { Authorization: auth };
  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "DELETE") {
    headers["Content-Type"] = "application/json";
    body = await request.text();
  }

  let res: Response;
  try {
    res = await fetch(upstream, {
      method: request.method,
      signal: AbortSignal.timeout(30_000),
      headers,
      body,
    });
  } catch (err) {
    console.error("admin proxy fetch failed", err instanceof Error ? err.message : String(err));
    return json({ error: "admin backend unreachable" }, 502);
  }

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
```

- [ ] **Step 2: Type-check / build**

Run: `npm run build`
Expected: build succeeds (no TS errors in the new function).

- [ ] **Step 3: Commit**

```bash
git add "functions/api/admin/[[path]].ts"
git commit -m "feat(website): admin allowlist API proxy (Pages Function)"
```

### Task 5: `/admin` page

**Files:**
- Create: `src/components/AdminAllowlist.tsx`
- Modify: `src/App.tsx` (add the `/admin` pathname early-return + import)
- Test: `src/components/AdminAllowlist.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/components/AdminAllowlist.test.tsx
// @vitest-environment jsdom
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminAllowlist from "./AdminAllowlist";

function mockFetchOnce(status: number, body: unknown) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdminAllowlist", () => {
  it("prompts for a token when none stored", () => {
    render(<AdminAllowlist />);
    expect(screen.getByPlaceholderText(/admin token/i)).toBeTruthy();
  });

  it("loads and renders the allowlist once a token is present", async () => {
    localStorage.setItem("gigaflow_admin_token", "t");
    mockFetchOnce(200, { emails: [{ email: "a@x.com", added_at: "2026-06-08T00:00:00Z" }] });
    render(<AdminAllowlist />);
    await waitFor(() => expect(screen.getByText("a@x.com")).toBeTruthy());
    const [url, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/admin/allowlist");
    expect((opts.headers as Record<string, string>).Authorization).toBe("Bearer t");
  });

  it("adds an email then re-fetches the list", async () => {
    localStorage.setItem("gigaflow_admin_token", "t");
    mockFetchOnce(200, { emails: [] });            // initial load
    render(<AdminAllowlist />);
    await waitFor(() =>
      expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1),
    );
    mockFetchOnce(200, { email: "new@x.com", added: true }); // POST
    mockFetchOnce(200, { emails: [{ email: "new@x.com", added_at: null }] }); // reload
    fireEvent.change(screen.getByPlaceholderText(/email@/i), { target: { value: "new@x.com" } });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    await waitFor(() => expect(screen.getByText("new@x.com")).toBeTruthy());
    const postCall = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1];
    expect(postCall[0]).toBe("/api/admin/allowlist");
    expect(postCall[1].method).toBe("POST");
  });

  it("shows an error on 401", async () => {
    localStorage.setItem("gigaflow_admin_token", "bad");
    mockFetchOnce(401, { error: "Invalid admin token." });
    render(<AdminAllowlist />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/components/AdminAllowlist.test.tsx`
Expected: FAIL — cannot resolve `./AdminAllowlist`.

- [ ] **Step 3: Write the component**

```tsx
// src/components/AdminAllowlist.tsx
import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "gigaflow_admin_token";

interface Entry {
  email: string;
  added_at: string | null;
}

export default function AdminAllowlist() {
  const [token, setToken] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem(TOKEN_KEY)) || "",
  );
  const [tokenInput, setTokenInput] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [newEmail, setNewEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/admin/allowlist", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        setError("Invalid or missing admin token.");
        setEntries([]);
        return;
      }
      if (!res.ok) {
        setError(`Failed to load (HTTP ${res.status}).`);
        return;
      }
      const data = await res.json();
      setEntries(data.emails ?? []);
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveToken = () => {
    const t = tokenInput.trim();
    if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    setToken(t);
  };

  const forgetToken = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setTokenInput("");
    setEntries([]);
    setError("");
  };

  const addEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = newEmail.trim();
    if (!email) return;
    setError("");
    try {
      const res = await fetch("/api/admin/allowlist", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (res.status === 401) {
        setError("Invalid or missing admin token.");
        return;
      }
      if (!res.ok) {
        setError(`Failed to add (HTTP ${res.status}).`);
        return;
      }
      setNewEmail("");
      await load();
    } catch {
      setError("Network error.");
    }
  };

  const removeEmail = async (email: string) => {
    setError("");
    try {
      const res = await fetch(`/api/admin/allowlist/${encodeURIComponent(email)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        setError("Invalid or missing admin token.");
        return;
      }
      if (!res.ok) {
        setError(`Failed to remove (HTTP ${res.status}).`);
        return;
      }
      await load();
    } catch {
      setError("Network error.");
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen bg-slate-950 text-white p-8 max-w-xl mx-auto">
        <h1 className="text-2xl font-semibold mb-2">Admin — Waitlist allowlist</h1>
        <p className="text-slate-400 mb-4">Enter the admin token to continue.</p>
        <div className="flex gap-2">
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Admin token"
            className="flex-1 rounded bg-slate-900 border border-slate-700 px-3 py-2"
          />
          <button
            onClick={saveToken}
            className="rounded bg-blue-600 hover:bg-blue-700 px-4 py-2"
          >
            Continue
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white p-8 max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Admin — Waitlist allowlist</h1>
        <button onClick={forgetToken} className="text-sm text-slate-400 hover:text-white underline">
          Forget token
        </button>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded bg-red-950 border border-red-800 px-3 py-2 text-red-200">
          {error}
        </p>
      )}

      <form onSubmit={addEmail} className="flex gap-2 mb-6">
        <input
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          placeholder="email@company.com"
          className="flex-1 rounded bg-slate-900 border border-slate-700 px-3 py-2"
        />
        <button type="submit" className="rounded bg-blue-600 hover:bg-blue-700 px-4 py-2">
          Add
        </button>
      </form>

      {loading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className="text-slate-400 border-b border-slate-800">
              <th className="py-2">Email</th>
              <th className="py-2">Added</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((row) => (
              <tr key={row.email} className="border-b border-slate-900">
                <td className="py-2">{row.email}</td>
                <td className="py-2 text-slate-400">{row.added_at ?? ""}</td>
                <td className="py-2 text-right">
                  <button
                    onClick={() => removeEmail(row.email)}
                    className="text-sm text-red-400 hover:text-red-300"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan={3} className="py-4 text-slate-500">
                  No allowlisted emails yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the `/admin` route in `src/App.tsx`**

Add the import near the other component imports (e.g. next to the `DemoPage` import):

```tsx
import AdminAllowlist from "./components/AdminAllowlist";
```

The current `App()` body is:

```tsx
export default function App() {
  return (
    <AuthProvider>
      ...
    </AuthProvider>
  );
}
```

Add the `/admin` early-return as the **first statement** inside `App()`, before
the `return (<AuthProvider>…`. The admin page needs none of the providers:

```tsx
export default function App() {
  if (typeof window !== "undefined" && window.location.pathname === "/admin") {
    return <AdminAllowlist />;
  }

  return (
    <AuthProvider>
```

(Leave the existing `isDemoRoute()` routing and the provider tree untouched.)

- [ ] **Step 5: Run tests + build**

Run: `npm run test -- src/components/AdminAllowlist.test.tsx`
Expected: PASS (4 tests).
Run: `npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 6: Commit**

```bash
git add src/components/AdminAllowlist.tsx src/components/AdminAllowlist.test.tsx src/App.tsx
git commit -m "feat(website): /admin allowlist management page"
```

---

## Self-Review

**Spec coverage:**
- `GIGAFLOW_ADMIN_TOKEN` setting → Task 1. ✓
- `require_admin` (Bearer, constant-time, 503 unset, 401 bad, dev-mode bypass) → Task 2. ✓
- `GET/POST/DELETE /api/v1/admin/allowlist`, reuse `AllowlistedEmail`, idempotent add/remove → Task 3. ✓
- Mounted outside customer gate, gated by `require_admin`, `Authorization: Bearer` transport → Task 3 (mount). ✓
- `/admin` page: token in `localStorage`, list/add/remove, 401 re-prompt, "Forget token" → Task 5. ✓
- Transport via same-origin proxy (spec refinement) → Task 4. ✓
- Tests (backend gate + endpoints; website page) → Tasks 2, 3, 5. ✓
- Rollout/merge order, env vars → plan header. ✓

**Placeholder scan:** none — every step has complete code + exact commands.

**Type/name consistency:** `require_admin` (Task 2) imported and mounted in Task 3. `AllowlistedEmail` reused (defined in the prior feature). Response shapes consistent: list `{emails:[{email,added_at}]}`, add `{email,added}`, delete `{email,removed}` — matched in backend tests (Task 3) and the website component/tests consume `data.emails` / `email` field (Task 5). The website proxy path `/api/admin/allowlist` (Task 4) matches the component's fetch URLs (Task 5). `TOKEN_KEY = "gigaflow_admin_token"` consistent between component and tests.

**Note on `result.rowcount`:** the add/delete endpoints report `(result.rowcount or 0) > 0`. Under asyncpg this reflects rows affected; backend tests mock it directly. The website doesn't depend on the `added`/`removed` boolean for correctness (it always re-fetches), so any driver nuance is non-breaking.
