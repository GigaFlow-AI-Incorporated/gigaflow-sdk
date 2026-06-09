# `gigaflow setup` — connection preflight & retry loop

**Date:** 2026-06-09
**Status:** Approved (design), pending implementation plan
**Repos:** `gigaflow` (backend), `gigaflow-sdk` (CLI)

## Problem

`gigaflow setup` registers a pull-model datasource (the GigaFlow backend connects
out to the user's tracing DB, e.g. Arize Phoenix's Postgres) and immediately syncs.
Today the flow has three failure modes that together make a bad connection look like
a broken product:

1. **No connectivity feedback.** A wrong host/port/credential surfaces only as a raw
   `502 Failed to connect to source DB: [Errno -2] …` during the in-wizard sync.
2. **Work is lost on failure.** `run_wizard` calls `_config.save()` as its *last* line,
   gated behind a successful `do_sync`. A failed sync → no `~/.gigaflow/config.json` is
   written → a later `gigaflow sync` reports "No configuration found." The symptom hides
   the real cause (the connection).
3. **Duplicates pile up.** Because config isn't saved, the user re-runs the whole wizard,
   which creates a *new* project and a *new* datasource each time (observed: 3 duplicate
   `arize_phoenix` datasources from 3 retries).

The pull model itself is correct: a team already running Arize/Phoenix has its traces in
a database, and exposing read access is less work than re-instrumenting an app to push.
Push is explicitly **out of scope** — the fix is to make the pull flow *guide* the user
through connectivity instead of failing cryptically.

## Goals

- Validate the source connection **from the backend's vantage point** before the wizard
  declares success, with a specific, actionable diagnosis.
- Let the user fix access interactively (retry / edit connection / save & quit) without
  losing work or creating duplicates.
- Persist config once access is good (or on explicit save & quit) so `gigaflow sync`
  works later with no re-wizard.

## Non-goals

- No push / direct-OTLP path in `setup` (deliberately rejected).
- No `DELETE /datasources/{id}` cleanup (noted follow-up; the 405 the user hit). The
  reorder below prevents *new* duplicates, which is the root issue.

## Design

### Flow (reordered)

```
collect connection
      │
      ▼
  PREFLIGHT ──fail──▶ show diagnosis + remediation
      │                 [r]etry / [e]dit connection / [q] save & quit
      │ ok                   │              │              │
      ▼                      └──────────────┘              │
  create project ◀───────────(on ok, or on save&quit)──────┘
  upload transform
  register datasource
  sync (skipped on save&quit-while-failing)
  save config
```

Creation (project + datasource) happens **only at the terminal step**: on a passing
preflight, or on an explicit *save & quit*. Abandoned retries/edits create nothing —
no orphan projects, no duplicate datasources. On *save & quit* while still failing, we
create + persist anyway and print remediation, so `gigaflow sync` works once access is
exposed.

### Backend — `POST /datasources/test` (`gigaflow`)

A healthcheck-style probe. No persistence, no ingest.

- **Body:** `{project_id, source_type, connection_url, source_table, api_key?}`.
  Authenticated and owner-scoped, like the other `/datasources` routes.
- **Behavior:** dispatch to the source reader's `healthcheck()`:
  - Postgres sources (`arize_phoenix`): `connect()` → `SELECT 1` → confirm the table
    exists (`SELECT 1 FROM <source_table> LIMIT 1`) → disconnect.
  - API sources (`logfire`, `braintrust`, `mlflow`): a minimal authed call against the
    base URL (auth/reachability only).
- **Response:** `{ok: bool, kind: str, detail: str, latency_ms: int}`.
- **`kind` enum:** `ok | host_unreachable | conn_refused | auth_failed | wrong_db |
  table_missing | timeout | unknown`. (`wrong_port` is **not** a backend kind — the
  backend can't reliably tell a wrong port from a refused/protocol error. It's a
  CLI-side heuristic, below.)
- **Classifier** (the only real logic, unit-tested in isolation) maps exception/errno →
  `kind`:
  - `socket.gaierror` / `[Errno -2]` / `[Errno -3]` → `host_unreachable`
  - `ConnectionRefusedError` / `[Errno 111]` → `conn_refused`
  - password/auth errors (`InvalidPassword`, `28P01`) → `auth_failed`
  - "database … does not exist" (`3D000`) → `wrong_db`
  - relation/table missing (`42P01`) → `table_missing`
  - timeouts → `timeout`
  - otherwise → `unknown` (with sanitized `detail`)
- **Secrets:** the password in `connection_url` is never logged; `detail` is sanitized.

### SDK — wizard reorder + retry loop (`gigaflow-sdk`, `_setup.py`)

- `preflight(base_url, source_type, connection_url, source_table, api_key) -> dict`
  calls `/datasources/test` and returns the parsed `{ok, kind, detail}`.
- `_REMEDIATION: dict[str, str]` maps each `kind` → tailored fix text, e.g.:
  - `host_unreachable` → "The GigaFlow backend can't resolve this host. If the DB is on
    your machine it isn't reachable from the hosted backend — expose it publicly or
    allow-list our egress IPs. (`host.docker.internal`/`localhost` only work against a
    local backend.)"
  - `conn_refused` → "Reached the host but nothing is listening on that port. Check the
    port and that the DB accepts remote connections."
  - `auth_failed` / `wrong_db` / `table_missing` → field-specific hints.
- **CLI-side `wrong_port` heuristic:** before calling preflight, if the entered port is a
  known OTLP port (`4317`/`4318`), warn "that looks like the OTLP port, not Postgres" and
  let the user correct it. Independent of the backend `kind`.
- Retry loop after `vendor.collect(env)`:
  ```
  while True:
      r = preflight(...)
      if r["ok"]: break
      show diagnosis (r["detail"]) + _REMEDIATION[r["kind"]]
      choice = prompt("[r]etry / [e]dit connection / [q] save & quit")
      if choice == "e": conn = vendor.collect(env)          # re-collect connection
      elif choice == "q": save_and_quit = True; break
      # "r" (default): loop and re-test
  ```
- Then create project → upload transform → register datasource → (sync unless
  `save_and_quit`) → `_config.save({backend_url, project_id, datasource_id, api_key?})`.
- The existing `_handle_setup` "Already configured" guard already prevents re-running the
  wizard once config exists — so the config-save fix closes the duplicate loop.

### Graceful degradation & rollout

- If `/datasources/test` returns 404 (older backend), the CLI **skips preflight** and
  falls through to the existing register→sync path. The CLI stays a thin client that
  tolerates a missing endpoint.
- **Merge order:** backend PR first (deploy `/datasources/test`), then the CLI PR.

## Error handling

- Preflight endpoint unreachable / non-200 (other than a clean `{ok:false,…}`): treat as
  "couldn't verify," warn, and let the user proceed (do not crash the wizard).
- All prompts tolerate EOF/non-interactive input (CI) by treating it as "quit."

## Testing

**Backend (`gigaflow`):**
- Classifier unit tests: each error/errno → expected `kind`.
- Endpoint tests: mock the reader's `connect()` to raise each error class → assert
  `kind` + non-200-free contract (endpoint returns 200 with `ok:false`, not an HTTP
  error, so the CLI can read `kind`); one `ok` path against the Postgres test fixture.

**SDK (`gigaflow-sdk`, `tests/test_setup_wizard_vendors.py`):**
- `preflight()` HTTP contract (monkeypatched `api()`).
- `kind` → remediation mapping coverage.
- Retry-loop control flow: fail-then-ok (proceeds), edit (re-collects), save & quit
  (creates + saves config, skips sync), and the 404 degradation path.

## Rollout summary

1. `gigaflow` PR: `/datasources/test` + reader `healthcheck()` + classifier + tests. Merge.
2. `gigaflow-sdk` PR: `preflight()`, remediation map, wizard reorder + retry loop,
   config-save fix, tests. Merge.
