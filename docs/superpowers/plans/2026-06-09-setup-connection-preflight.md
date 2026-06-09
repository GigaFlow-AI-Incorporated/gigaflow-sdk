# `gigaflow setup` Connection Preflight & Retry Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gigaflow setup`'s pull-model datasource flow validate connectivity from the backend's vantage point before declaring success, guide the user through fixing access with an interactive retry loop, and stop losing config / creating duplicate datasources on failure.

**Architecture:** A new healthcheck-style `POST /datasources/test` backend endpoint (returns `{ok, kind, detail, latency_ms}`, classifying connect/query errors into a stable `kind` enum) plus a reordered CLI wizard (`collect → preflight (retry/edit/save&quit) → create → sync`) that creates nothing until the connection is good or the user explicitly saves & quits.

**Tech Stack:** FastAPI + asyncpg + pytest-asyncio (backend `gigaflow`); zero-dependency stdlib Python CLI + pytest (`gigaflow-sdk`).

**Spec:** `docs/superpowers/specs/2026-06-09-setup-connection-preflight-design.md` (in `gigaflow-sdk`).

**Scope note (deviation from spec):** v1 backend healthcheck implements the **Postgres** path (`arize_phoenix`, the demonstrated failure). Non-Postgres source types return `kind="skipped"`, `ok=true` so the CLI proceeds normally. API-reader (logfire/braintrust/mlflow/wb_weave) healthchecks are a tracked follow-up — recorded as a GitHub issue at the end.

**Merge order:** Phase A (backend) merges first; the CLI degrades gracefully if `/datasources/test` 404s. Then Phase B (CLI).

---

## Phase A — Backend: `POST /datasources/test`

**Repo:** `gigaflow`. **Branch:** `feat/datasource-test-endpoint` (create a fresh worktree first).

### Task A0: Create the backend worktree

- [ ] **Step 1: Create an isolated worktree + branch**

Run (from the main `gigaflow` checkout):
```bash
cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow
git fetch origin -q
git worktree add .claude/worktrees/ds-test -b feat/datasource-test-endpoint origin/main
cd .claude/worktrees/ds-test
git branch --show-current   # expect: feat/datasource-test-endpoint
```

### Task A1: Connection-test classifier + probe (pure-ish module)

**Files:**
- Create: `backend/app/datasources/connection_test.py`
- Test: `backend/tests/datasources/test_connection_test.py`

- [ ] **Step 1: Write the failing classifier tests**

Create `backend/tests/datasources/test_connection_test.py`:
```python
"""Unit tests for the datasource connection-test classifier."""
import asyncio
import socket

from app.datasources.connection_test import classify_db_error


def _err(exc, *, sqlstate=None, errno=None, cause=None):
    if sqlstate is not None:
        exc.sqlstate = sqlstate
    if errno is not None:
        exc.errno = errno
    if cause is not None:
        exc.__cause__ = cause
    return exc


def test_host_unreachable_from_gaierror():
    assert classify_db_error(socket.gaierror(-2, "Name or service not known")) == "host_unreachable"


def test_host_unreachable_from_wrapped_gaierror():
    wrapped = _err(OSError("connect failed"), cause=socket.gaierror(-2, "Name or service not known"))
    assert classify_db_error(wrapped) == "host_unreachable"


def test_conn_refused_from_errno_111():
    assert classify_db_error(ConnectionRefusedError(111, "Connection refused")) == "conn_refused"


def test_auth_failed_from_sqlstate():
    assert classify_db_error(_err(Exception("nope"), sqlstate="28P01")) == "auth_failed"


def test_wrong_db_from_sqlstate():
    assert classify_db_error(_err(Exception("nope"), sqlstate="3D000")) == "wrong_db"


def test_table_missing_from_sqlstate():
    assert classify_db_error(_err(Exception("nope"), sqlstate="42P01")) == "table_missing"


def test_timeout():
    assert classify_db_error(asyncio.TimeoutError()) == "timeout"


def test_unknown_fallback():
    assert classify_db_error(Exception("something weird")) == "unknown"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend pytest tests/datasources/test_connection_test.py -v`
Expected: FAIL with `ModuleNotFoundError: app.datasources.connection_test`.

- [ ] **Step 3: Implement the classifier + probe**

Create `backend/app/datasources/connection_test.py`:
```python
"""Healthcheck-style connection test for pull-model datasources.

Used by ``POST /api/v1/datasources/test`` to validate that the GigaFlow backend
can actually reach a source before the CLI wizard registers it. No persistence,
no ingest — connect, trivial probe, classify any failure into a stable ``kind``.
"""
import asyncio
import socket
import time

import asyncpg

# Stable kinds the CLI maps to remediation text. Keep in sync with the CLI's
# _REMEDIATION map in gigaflow-sdk/gigaflow/_setup.py.
KINDS = (
    "ok", "skipped", "host_unreachable", "conn_refused",
    "auth_failed", "wrong_db", "table_missing", "timeout", "unknown",
)

_CONNECT_TIMEOUT_S = 8.0


def _causes(exc: BaseException):
    """Yield the exception and its __cause__/__context__ chain (bounded)."""
    seen = 0
    cur: BaseException | None = exc
    while cur is not None and seen < 5:
        yield cur
        seen += 1
        cur = cur.__cause__ or cur.__context__


def classify_db_error(exc: BaseException) -> str:
    """Map a connect/query exception to a stable ``kind`` string."""
    for e in _causes(exc):
        sqlstate = getattr(e, "sqlstate", None)
        if sqlstate in ("28P01", "28000"):
            return "auth_failed"
        if sqlstate == "3D000":
            return "wrong_db"
        if sqlstate == "42P01":
            return "table_missing"
        if isinstance(e, asyncio.TimeoutError):
            return "timeout"
        if isinstance(e, socket.gaierror) or getattr(e, "errno", None) in (-2, -3):
            return "host_unreachable"
        if isinstance(e, ConnectionRefusedError) or getattr(e, "errno", None) == 111:
            return "conn_refused"
        msg = str(e).lower()
        if "name or service not known" in msg or "nodename nor servname" in msg \
                or "temporary failure in name resolution" in msg:
            return "host_unreachable"
        if "connection refused" in msg:
            return "conn_refused"
        if "password authentication failed" in msg or "authentication failed" in msg:
            return "auth_failed"
        if "does not exist" in msg and "database" in msg:
            return "wrong_db"
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
    return "unknown"


def _sanitize(detail: str, connection_url: str | None) -> str:
    """Strip a password out of any echoed connection string in the detail."""
    if connection_url and "@" in connection_url and "://" in connection_url:
        creds = connection_url.split("://", 1)[1].split("@", 1)[0]
        if ":" in creds:
            pw = creds.split(":", 1)[1]
            if pw:
                detail = detail.replace(pw, "***")
    return detail[:300]


async def _postgres_healthcheck(connection_url: str, source_table: str) -> tuple[str, str]:
    """Connect, SELECT 1, confirm the table exists. Returns (kind, detail)."""
    try:
        conn = await asyncio.wait_for(asyncpg.connect(connection_url), timeout=_CONNECT_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - we classify, not swallow
        return classify_db_error(e), _sanitize(str(e), connection_url)
    try:
        await conn.fetchval("SELECT 1")
        try:
            await conn.fetchval(f'SELECT 1 FROM "{source_table}" LIMIT 1')
        except Exception as e:  # noqa: BLE001
            kind = classify_db_error(e)
            return (kind if kind != "unknown" else "table_missing"), _sanitize(str(e), connection_url)
    finally:
        await conn.close()
    return "ok", ""


async def run_healthcheck(source_type: str, connection_url: str, source_table: str) -> tuple[str, str]:
    """Dispatch by source_type. Non-Postgres sources are skipped in v1."""
    if source_type in ("arize_phoenix", "", None):
        return await _postgres_healthcheck(connection_url, source_table or "spans")
    return "skipped", f"preflight not implemented for source_type={source_type!r}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend pytest tests/datasources/test_connection_test.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Lint**

Run: `docker compose exec backend ruff check app/datasources/connection_test.py tests/datasources/test_connection_test.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/datasources/connection_test.py backend/tests/datasources/test_connection_test.py
git commit -m "feat(datasources): connection-test classifier + Postgres healthcheck probe"
```

### Task A2: The `POST /datasources/test` endpoint

**Files:**
- Modify: `backend/app/api/routers/datasources.py` (add request model + route after `register_datasource`, ~line 161)
- Test: `backend/tests/api/test_datasources.py`

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/api/test_datasources.py` (match the file's existing AsyncMock/DB-mock style; if helpers like `make_app`/`client`/`mock_db` exist, reuse them — read the top of the file first):
```python
import app.api.routers.datasources as ds_router


async def test_datasource_test_ok(monkeypatch, client, mock_owned_project):
    # mock_owned_project: a Project fixture the auth/ownership path resolves to.
    async def fake_run_healthcheck(source_type, connection_url, source_table):
        return ("ok", "")
    monkeypatch.setattr(ds_router, "run_healthcheck", fake_run_healthcheck)

    resp = await client.post("/api/v1/datasources/test", json={
        "project_id": str(mock_owned_project.project_id),
        "source_type": "arize_phoenix",
        "connection_url": "postgresql://postgres:postgres@db:5432/postgres",
        "source_table": "spans",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["kind"] == "ok"
    assert "latency_ms" in body


async def test_datasource_test_host_unreachable_is_200_not_502(monkeypatch, client, mock_owned_project):
    async def fake_run_healthcheck(source_type, connection_url, source_table):
        return ("host_unreachable", "[Errno -2] Name or service not known")
    monkeypatch.setattr(ds_router, "run_healthcheck", fake_run_healthcheck)

    resp = await client.post("/api/v1/datasources/test", json={
        "project_id": str(mock_owned_project.project_id),
        "source_type": "arize_phoenix",
        "connection_url": "postgresql://postgres:postgres@host.docker.internal:58999/postgres",
        "source_table": "spans",
    })
    # Connection failure is a 200 with ok:false so the CLI can read `kind`.
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["kind"] == "host_unreachable"
```

NOTE: read the top ~60 lines of `tests/api/test_datasources.py` and `tests/api/conftest.py` first to use the actual `client` / project-ownership fixtures and auth-bypass already in place; adapt fixture names above to match.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend pytest tests/api/test_datasources.py -k datasource_test -v`
Expected: FAIL with 404/route-not-found.

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routers/datasources.py`, add the import near the other datasource imports (after line 29):
```python
from app.datasources.connection_test import run_healthcheck
```

Add the request model after `DataSourceCreate` (after line 105):
```python
class DataSourceTest(BaseModel):
    project_id: UUID
    connection_url: str
    source_table: str = "spans"
    source_type: str = "arize_phoenix"
    api_key: Optional[str] = None
```

Add the route immediately after `register_datasource` (after line 160):
```python
@router.post("/test")
async def test_datasource_connection(
    body: DataSourceTest,
    db: AsyncSession = Depends(get_traces_db),
    user_id: UUID | None = Depends(get_current_user),
):
    """Healthcheck a prospective datasource connection without persisting anything.

    Returns 200 with ``{ok, kind, detail, latency_ms}`` even when the connection
    fails (so the CLI can read ``kind`` and render remediation). Only a missing /
    unowned project (404) or unauthenticated caller short-circuits as an HTTP error.
    """
    result = await db.execute(select(Project).filter(Project.project_id == body.project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if user_id is not None and project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")

    import time as _time
    start = _time.monotonic()
    kind, detail = await run_healthcheck(body.source_type, body.connection_url, body.source_table)
    latency_ms = int((_time.monotonic() - start) * 1000)
    return {"ok": kind in ("ok", "skipped"), "kind": kind, "detail": detail, "latency_ms": latency_ms}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend pytest tests/api/test_datasources.py -k datasource_test -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full datasources + connection-test suites + lint**

Run:
```bash
docker compose exec backend pytest tests/api/test_datasources.py tests/datasources/test_connection_test.py -q
docker compose exec backend ruff check app/api/routers/datasources.py
```
Expected: all pass, no lint errors.

- [ ] **Step 6: Update docs**

In `backend/CLAUDE.md`, under the datasources section, add one line documenting `POST /api/v1/datasources/test` (healthcheck, returns `{ok, kind, detail, latency_ms}`, 200 even on connection failure). In `docs/otlp-quickstart.md` no change needed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routers/datasources.py backend/tests/api/test_datasources.py backend/CLAUDE.md
git commit -m "feat(datasources): POST /datasources/test connection healthcheck endpoint"
```

### Task A3: Open the backend PR

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/datasource-test-endpoint
gh pr create --fill --title "feat(datasources): connection preflight endpoint (POST /datasources/test)" \
  --body "Adds a healthcheck-style connection test so the CLI setup wizard can validate a pull-model datasource before registering it. Returns {ok, kind, detail, latency_ms}; 200 even on connection failure so the client can render remediation. Postgres (arize_phoenix) path implemented; other source types return kind=skipped (follow-up). Part 1 of 2 (CLI PR follows). Spec: gigaflow-sdk docs/superpowers/specs/2026-06-09-setup-connection-preflight-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 2: Stop for review.** Backend PR must merge + deploy before the CLI PR is useful. Hand back to the user for review/merge.

---

## Phase B — CLI: wizard reorder + retry loop

**Repo:** `gigaflow-sdk`. **Branch:** `feat/setup-connection-preflight` (worktree already created at `.claude/worktrees/setup-preflight`).

### Task B1: `preflight()` + remediation map + wrong-port heuristic

**Files:**
- Modify: `gigaflow/_setup.py`
- Test: `tests/test_setup_wizard_vendors.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_wizard_vendors.py`:
```python
def test_preflight_returns_parsed_result(monkeypatch):
    captured = {}
    def fake_api(base_url, method, path, body=None, **kw):
        captured["path"] = path
        captured["body"] = body
        return (200, {"ok": False, "kind": "host_unreachable", "detail": "[Errno -2]", "latency_ms": 12})
    monkeypatch.setattr(setup_mod, "api", fake_api)
    r = setup_mod.preflight("http://b/api/v1", "arize_phoenix",
                            "postgresql://u:p@h:5432/d", "spans", None)
    assert r == {"ok": False, "kind": "host_unreachable", "detail": "[Errno -2]"}
    assert captured["path"] == "/datasources/test"
    assert captured["body"]["connection_url"] == "postgresql://u:p@h:5432/d"


def test_preflight_404_degrades_to_skipped(monkeypatch):
    # Older backend without the endpoint → CLI must not block setup.
    monkeypatch.setattr(setup_mod, "api", lambda *a, **k: (404, {"detail": "Not Found"}))
    r = setup_mod.preflight("http://b/api/v1", "arize_phoenix", "x", "spans", None)
    assert r["ok"] is True and r["kind"] == "skipped"


def test_preflight_connection_error_degrades(monkeypatch):
    monkeypatch.setattr(setup_mod, "api", lambda *a, **k: (None, {}))
    r = setup_mod.preflight("http://b/api/v1", "arize_phoenix", "x", "spans", None)
    assert r["ok"] is True and r["kind"] == "skipped"


def test_remediation_covers_every_kind():
    for kind in ("host_unreachable", "conn_refused", "auth_failed",
                 "wrong_db", "table_missing", "timeout", "unknown"):
        assert kind in setup_mod._REMEDIATION
        assert setup_mod._REMEDIATION[kind].strip()


def test_is_otlp_port_heuristic():
    assert setup_mod._is_otlp_port("4317") is True
    assert setup_mod._is_otlp_port("4318") is True
    assert setup_mod._is_otlp_port("5432") is False
    assert setup_mod._is_otlp_port("") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-preflight && uv run pytest tests/test_setup_wizard_vendors.py -k "preflight or remediation or otlp_port" -v`
Expected: FAIL (`AttributeError: module 'gigaflow._setup' has no attribute 'preflight'`).

- [ ] **Step 3: Implement preflight + maps**

In `gigaflow/_setup.py`, add after `_resolve_key` (after line 176):
```python
_REMEDIATION = {
    "host_unreachable": (
        "The GigaFlow backend can't resolve this host. If the database is on your "
        "machine it is NOT reachable from the hosted backend — expose it publicly "
        "(or allow-list GigaFlow's egress IPs). 'host.docker.internal' / 'localhost' "
        "only work against a backend running on this same machine."
    ),
    "conn_refused": (
        "Reached the host but nothing is listening on that port. Check the port and "
        "that the database accepts remote TCP connections (Postgres listen_addresses / "
        "firewall / security group)."
    ),
    "auth_failed": "Authentication failed — check the user and password.",
    "wrong_db": "That database name doesn't exist on the server — check the DB name.",
    "table_missing": (
        "Connected and authenticated, but the source table wasn't found — check the "
        "table name (Arize Phoenix uses 'spans')."
    ),
    "timeout": (
        "The connection timed out. The host may be firewalled from the GigaFlow "
        "backend, or behind a VPC without a public route."
    ),
    "unknown": "Couldn't connect. See the detail above and verify each field.",
}

_OTLP_PORTS = {"4317", "4318"}


def _is_otlp_port(port: str) -> bool:
    return (port or "").strip() in _OTLP_PORTS


def preflight(base_url, source_type, connection_url, source_table, api_key) -> dict:
    """Ask the backend to healthcheck a prospective connection.

    Returns ``{ok, kind, detail}``. Degrades to ``{ok: True, kind: "skipped"}``
    when the endpoint is missing (404, older backend) or unreachable, so setup
    never hard-blocks on the preflight itself.
    """
    status, resp = api(
        base_url, "POST", "/datasources/test",
        {
            "project_id": "00000000-0000-0000-0000-000000000000",  # replaced below
        },
        api_key=_resolve_key(api_key),
    ) if False else (None, None)  # placeholder; real call built below
    # Build the real body (project_id is not required by the endpoint's probe,
    # but the model requires it; the wizard passes a real project_id via kwargs).
    raise NotImplementedError  # replaced in Step 3b
```

- [ ] **Step 3b: Fix the project_id contract**

The endpoint's `DataSourceTest` model requires `project_id`, but preflight runs *before* the project is created (per the reorder). Resolve by making the wizard create the project's *name* choice independent of preflight, and having preflight accept an explicit `project_id`. Simplest: the endpoint requires a project the caller owns; in the reordered wizard we **create the project first, then preflight, then register the datasource** — projects are cheap and a failed preflight leaves only an empty project (acceptable; far better than duplicate datasources). Update the design assumption: *project* is created before preflight; *datasource* is created only on ok/save&quit.

Replace the Step-3 stub with the final implementation:
```python
def preflight(base_url, project_id, source_type, connection_url, source_table, api_key) -> dict:
    """Ask the backend to healthcheck a prospective connection.

    Returns ``{ok, kind, detail}``. Degrades to ``{ok: True, kind: "skipped"}``
    when the endpoint is missing (404) or unreachable, so setup never hard-blocks
    on the preflight itself.
    """
    body = {
        "project_id": project_id,
        "source_type": source_type,
        "connection_url": connection_url,
        "source_table": source_table,
    }
    if api_key:
        body["api_key"] = api_key
    status, resp = api(base_url, "POST", "/datasources/test", body, api_key=_resolve_key(api_key))
    if status == 200 and isinstance(resp, dict):
        return {"ok": bool(resp.get("ok")), "kind": resp.get("kind", "unknown"),
                "detail": resp.get("detail", "")}
    # Missing endpoint / unreachable / unexpected → don't block setup.
    return {"ok": True, "kind": "skipped", "detail": ""}
```

Adjust the Step-1 tests to pass `project_id` as the 2nd arg: change `setup_mod.preflight("http://b/api/v1", "arize_phoenix", ...)` to `setup_mod.preflight("http://b/api/v1", "PID", "arize_phoenix", ...)` in all three preflight tests.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k "preflight or remediation or otlp_port" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/_setup.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): preflight() helper, remediation map, OTLP-port heuristic"
```

### Task B2: Wizard reorder + interactive retry loop

**Files:**
- Modify: `gigaflow/_setup.py` (`run_wizard`, lines 256-344)
- Test: `tests/test_setup_wizard_vendors.py`

- [ ] **Step 1: Write the failing retry-loop test**

Add a focused test of the loop helper (extract the loop into a testable function `_connection_retry_loop`). Append to `tests/test_setup_wizard_vendors.py`:
```python
def test_retry_loop_proceeds_when_ok(monkeypatch):
    calls = {"n": 0}
    def fake_preflight(*a, **k):
        calls["n"] += 1
        return {"ok": True, "kind": "ok", "detail": ""}
    monkeypatch.setattr(setup_mod, "preflight", fake_preflight)
    conn = {"connection_url": "postgresql://u:p@h:5432/d", "source_table": "spans", "api_key": None}
    outcome, conn2 = setup_mod._connection_retry_loop(
        "http://b/api/v1", "PID", "arize_phoenix", conn, env={}, recollect=lambda env: conn)
    assert outcome == "ok" and calls["n"] == 1


def test_retry_loop_retries_then_ok(monkeypatch):
    results = iter([
        {"ok": False, "kind": "conn_refused", "detail": "x"},
        {"ok": True, "kind": "ok", "detail": ""},
    ])
    monkeypatch.setattr(setup_mod, "preflight", lambda *a, **k: next(results))
    _install_prompts(monkeypatch, ["r"])  # choose retry once
    conn = {"connection_url": "postgresql://u:p@h:5432/d", "source_table": "spans", "api_key": None}
    outcome, _ = setup_mod._connection_retry_loop(
        "http://b/api/v1", "PID", "arize_phoenix", conn, env={}, recollect=lambda env: conn)
    assert outcome == "ok"


def test_retry_loop_save_and_quit(monkeypatch):
    monkeypatch.setattr(setup_mod, "preflight",
                        lambda *a, **k: {"ok": False, "kind": "host_unreachable", "detail": "x"})
    _install_prompts(monkeypatch, ["q"])  # save & quit
    conn = {"connection_url": "postgresql://u:p@h:5432/d", "source_table": "spans", "api_key": None}
    outcome, _ = setup_mod._connection_retry_loop(
        "http://b/api/v1", "PID", "arize_phoenix", conn, env={}, recollect=lambda env: conn)
    assert outcome == "save_and_quit"


def test_retry_loop_edit_recollects(monkeypatch):
    results = iter([
        {"ok": False, "kind": "wrong_db", "detail": "x"},
        {"ok": True, "kind": "ok", "detail": ""},
    ])
    monkeypatch.setattr(setup_mod, "preflight", lambda *a, **k: next(results))
    _install_prompts(monkeypatch, ["e"])  # edit → recollect, then loop re-tests → ok
    recollected = {"connection_url": "postgresql://u:p2@h2:5432/d2", "source_table": "spans", "api_key": None}
    conn = {"connection_url": "postgresql://u:p@h:5432/d", "source_table": "spans", "api_key": None}
    outcome, conn2 = setup_mod._connection_retry_loop(
        "http://b/api/v1", "PID", "arize_phoenix", conn, env={}, recollect=lambda env: recollected)
    assert outcome == "ok" and conn2["connection_url"] == recollected["connection_url"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k retry_loop -v`
Expected: FAIL (`no attribute '_connection_retry_loop'`).

- [ ] **Step 3: Implement the retry loop**

In `gigaflow/_setup.py`, add before `run_wizard` (before line 256):
```python
def _connection_retry_loop(base_url, project_id, source_type, conn, env, recollect):
    """Preflight the connection, looping on failure.

    ``recollect(env) -> conn`` re-runs the vendor's connection collector (for the
    'edit' choice). Returns ``(outcome, conn)`` where outcome is "ok" or
    "save_and_quit". The caller creates the datasource in both cases (so save&quit
    still persists config); only the sync is skipped on save&quit.
    """
    while True:
        # CLI-side wrong-port heuristic (Postgres only): warn before the round-trip.
        if source_type in ("arize_phoenix", "", None):
            port = conn["connection_url"].rsplit(":", 1)[-1].split("/")[0]
            if _is_otlp_port(port):
                _fmt.warn(f"Port {port} looks like the OTLP port, not Postgres — "
                          f"Arize Phoenix's Postgres usually isn't on {port}.")
        r = preflight(base_url, project_id, source_type,
                      conn["connection_url"], conn["source_table"], conn["api_key"])
        if r["ok"]:
            if r["kind"] == "ok":
                _fmt.ok("Source connection verified")
            return "ok", conn
        _fmt.fail(f"Could not connect ({r['kind']}).")
        if r.get("detail"):
            _fmt.info(r["detail"])
        _fmt.info(_REMEDIATION.get(r["kind"], _REMEDIATION["unknown"]))
        choice = (_fmt.prompt("[r]etry / [e]dit connection / [q] save & quit", "r") or "r").lower()
        if choice.startswith("q"):
            return "save_and_quit", conn
        if choice.startswith("e"):
            conn = recollect(env)
        # "r" or anything else → loop and re-test
```

- [ ] **Step 4: Run the loop tests to verify they pass**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k retry_loop -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire the loop into `run_wizard`**

In `gigaflow/_setup.py`, edit `run_wizard`. Replace the Step 3→6 region (current lines 281-331, from `# Step 3: connection` through the `do_sync` result handling) with the reordered flow:
```python
    # Step 3: connection (vendor-specific)
    _fmt.section("Step 3: Connection")
    conn = vendor.collect(env)

    # Step 4: project (created before preflight so the test endpoint has an owner)
    _fmt.section("Step 4: Project")
    print()
    print("  GigaFlow groups your traces under a *project* (a container in GigaFlow).")
    print()
    suggested = conn.get("vendor_project_name") or env.get("GIGAFLOW_PROJECT_NAME") or f"{vendor.key}-project"
    project_name = _fmt.prompt("GigaFlow project name", suggested)
    project_id = create_project(base_url, project_name, api_key)
    if not project_id:
        return None

    # Step 5: connection preflight (interactive retry loop)
    _fmt.section("Step 5: Connection check")
    outcome, conn = _connection_retry_loop(
        base_url, str(project_id), vendor.key, conn, env, recollect=vendor.collect)

    # Step 6: transform (vendor built-in by default)
    _fmt.section("Step 6: Transform")
    label = vendor.label.split("(")[0].strip()
    transform_path = _fmt.prompt(
        f"Path to transform.yml (leave blank for built-in {label} config)",
        env.get("GIGAFLOW_TRANSFORM_YML", ""),
    )
    if transform_path:
        try:
            with open(transform_path) as f:
                yaml_content = f.read()
            _fmt.ok(f"Loaded transform file: {transform_path}")
        except OSError as e:
            _fmt.fail(f"Could not read transform file: {e}")
            return None
    else:
        yaml_content = _load_transform(vendor.transform_file)
        _fmt.info(f"Using built-in {vendor.key} transform config")
        if vendor.key == "wb_weave":
            _fmt.info("Note: the W&B Weave transform is a TEMPLATE — verify the preview below.")
    if not upload_transform(base_url, project_id, yaml_content, api_key):
        return None

    # Step 7: register datasource (always), then sync unless we're saving & quitting
    _fmt.section("Step 7: Register datasource & sync")
    datasource_id = register_datasource(
        base_url, project_id, conn["connection_url"], conn["source_table"],
        api_key=conn["api_key"], source_type=vendor.key, name=vendor.key,
    )
    if not datasource_id:
        return None

    if outcome == "save_and_quit":
        _fmt.info("Saved without syncing — fix source access, then run:  gigaflow sync")
    else:
        result = do_sync(base_url, datasource_id, api_key)
        if result is None:
            # Connection passed preflight but sync still failed — save config anyway
            # so the user can retry sync without re-running the wizard.
            _fmt.info("Sync failed after a successful connection check — run:  gigaflow sync")
        else:
            synced_traces, _ = result
            if synced_traces > 0:
                ok = _preview_and_confirm(base_url, project_id, api_key)
                if not ok:
                    _fmt.info("You can supply a custom transform and re-run:")
                    _fmt.info("  gigaflow config clear  &&  gigaflow setup")
                    _fmt.info("  (point the transform prompt at your own transform.yml)")
```

The existing config-save tail (current lines 339-344) stays as-is and now runs in **all** terminal paths (ok or save&quit):
```python
    config: dict = {"backend_url": base_url, "project_id": project_id, "datasource_id": datasource_id}
    if api_key:
        config["api_key"] = api_key
    _config.save(config)
    _fmt.ok(f"Configuration saved to {_config.CONFIG_PATH}")
    return config
```

- [ ] **Step 6: Run the full wizard test suite**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -v`
Expected: PASS. If existing tests asserted the old step ordering / step labels (e.g. "Step 4: Project" text or call order of `create_project` vs `register_datasource`), update those assertions to the new order — the reorder is intentional.

- [ ] **Step 7: Run the whole SDK suite + lint**

Run:
```bash
uv run pytest -q
uv run ruff check gigaflow/_setup.py tests/test_setup_wizard_vendors.py
```
Expected: all pass, no lint errors.

- [ ] **Step 8: Update docs**

In `gigaflow-sdk/CLAUDE.md`, update the `setup` command bullet to mention the connection preflight + retry loop and that config is saved even when the source isn't reachable yet (so `gigaflow sync` can be retried). Note in the `sync` bullet that "No configuration found" no longer results from a failed first sync.

- [ ] **Step 9: Commit**

```bash
git add gigaflow/_setup.py tests/test_setup_wizard_vendors.py CLAUDE.md
git commit -m "feat(setup): reorder wizard around connection preflight + retry loop; save config on save&quit"
```

### Task B3: Open the CLI PR

- [ ] **Step 1: Push + PR (after the backend PR is merged + deployed)**

```bash
git push -u origin feat/setup-connection-preflight
gh pr create --fill --title "feat(setup): connection preflight + interactive retry loop" \
  --body "Reworks 'gigaflow setup' so a pull-model connection is verified from the backend's vantage point before the wizard finishes. On failure: a specific diagnosis + remediation and a [r]etry / [e]dit / [q] save&quit loop. Creation is deferred so abandoned attempts leave no duplicate datasources, and config is saved even on save&quit so 'gigaflow sync' works once access is exposed — fixing the 'No configuration found' + duplicate-datasource failure modes. Degrades gracefully if the backend lacks POST /datasources/test. Requires the backend PR (POST /datasources/test) merged first. Spec: docs/superpowers/specs/2026-06-09-setup-connection-preflight-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 2: Hand back to the user for review/merge.**

---

## Self-Review

**Spec coverage:**
- Connectivity preflight from backend vantage → Task A1/A2 (`/datasources/test`). ✓
- `kind` enum + classifier → Task A1. ✓ (`wrong_port` dropped from backend per spec amendment; CLI heuristic → Task B1/B2.) ✓
- Don't lose work / no duplicates → Task B2 (deferred creation + config saved in all terminal paths). ✓
- Interactive retry (retry/edit/save&quit) → Task B2 `_connection_retry_loop`. ✓
- Per-`kind` remediation text → Task B1 `_REMEDIATION`. ✓
- Graceful 404 degradation, backend-first merge → Task B1 (`preflight` skipped) + A3/B3 ordering. ✓
- Secrets never logged → Task A1 `_sanitize`. ✓
- Out of scope: push, DELETE cleanup, API-reader healthchecks → noted; follow-up issue below. ✓

**Spec amendment:** v1 backend healthcheck is Postgres-only; API readers return `kind="skipped"`. The spec's "generic minimal authed call for API readers" is deferred. (Recorded as a follow-up issue.)

**Placeholder scan:** No TBD/TODO; the only stub (Step B1-3) is explicitly replaced in B1-3b with full code. ✓

**Type consistency:** `kind` strings identical across backend `KINDS`, classifier returns, and CLI `_REMEDIATION` keys. `preflight(base_url, project_id, source_type, connection_url, source_table, api_key)` signature consistent between B1 (final form) and B2 callers. `_connection_retry_loop(base_url, project_id, source_type, conn, env, recollect)` consistent between definition and tests. ✓

## Follow-up issues to file (per repo convention)
1. **gigaflow:** `DELETE /api/v1/datasources/{id}` (owner-scoped) — the 405 the user hit; needed to clean up stale/duplicate datasources. Add a `gigaflow datasources rm` CLI wrapper.
2. **gigaflow:** Extend `/datasources/test` healthchecks to API readers (logfire/braintrust/mlflow/wb_weave) — v1 returns `kind=skipped` for these.
