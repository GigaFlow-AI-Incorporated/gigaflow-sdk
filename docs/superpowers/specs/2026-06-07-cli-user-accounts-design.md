# Per-user accounts for the gigaflow CLI

**Date:** 2026-06-07
**Status:** Approved (design)
**Scope:** cross-repo — `gigaflow-sdk` (CLI), `gigaflow` (backend), `gigaflow-website` (UI), plus Supabase project config.

## Goal

Give the CLI a real per-user identity so that:

1. `pip install gigaflow`
2. First backend-touching run with no credentials tells the user to sign up at
   https://api.gigaflow.io and run `gigaflow login`.
3. `gigaflow login` (email + password) stores credentials locally.
4. Every trace the CLI uploads is **owned by that account**.
5. Logging into the web UI as the same account shows exactly those traces.

## Context: what already exists (do not rebuild)

- **Identity is already Supabase Auth.** The backend treats the Supabase user
  `sub` UUID as the system of record. There is **no users table**; ownership is a
  `user_id` column on owned rows.
- **Backend already verifies Supabase JWTs.** `app/api/deps/supabase_auth.py`
  (`get_current_user`) accepts *either* a Supabase JWT (→ `UUID(sub)`) *or* the
  static `FLOW_COMPUTE_API_KEY` (→ `None`, service caller). Written and tested.
  It supports HS256 (shared secret) and RS256/ES256 (JWKS). `GIGAFLOW_DEV_MODE`
  short-circuits to `None`.
- **`Trace.user_id`** already exists (nullable, indexed), stamped by the website
  "Analyze a trace" path (`app/api/routers/web_ingest.py`), which also
  auto-provisions a per-user `web:<user_id>` project.
- **The website already signs users up** via Supabase email magic-link/OTP
  (`signInWithOtp` in `src/contexts/AuthContext.tsx`), and ships the anon key to
  the browser (`src/lib/supabase.ts`).
- **App data lives in RDS Postgres** (`gigaflow-infra/rds.tf`). Supabase is used
  purely as a standalone identity provider — it issues JWTs, the backend
  verifies them. Clean separation; keep it.

### The gap

- The CLI is identity-less. `gigaflow setup` stores a single shared `api_key` in
  `~/.gigaflow/config.json`; the backend accepts it as the static service key →
  `user_id = None` → **uploads are not attached to any user**.
- `Project` has **no owner column**.
- The projects/traces **read endpoints do not filter by user** — they sit behind
  the static-key gate and return everything.

## Decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Identity provider | **Keep Supabase** | Already integrated + tested; password reset, email verify, refresh rotation, future SSO/MFA are config, not code. App data stays in RDS. |
| Login credential | **Email + password** | Supabase supports it natively; CLI login is a single password-grant HTTP call, no browser, works headless. |
| Account creation | **Browser signup at api.gigaflow.io**, CLI does login only | Matches Vercel/GitHub/Supabase CLIs; reuses the existing website signup. |
| Ownership granularity | **Project owns traces** | Every trace in a project (supplement, sync, long-lived OTLP token) inherits the project owner. Handles OTLP tokens cleanly (token → project → owner). |

### Explicitly out of scope (YAGNI)

- No users table (Supabase `sub` remains the key).
- No OS-keychain storage yet (file at `0600`; keychain is a later enhancement).
- No per-trace attribution within shared projects, no teams/orgs, no SSO/MFA.
- The static service key is **not** ripped out — it stays as a dev/self-host
  fallback.

---

## Component 1 — SDK / CLI (`gigaflow-sdk`)

### Credential store

New file `~/.gigaflow/credentials.json`, permissions `0600`, **separate** from
`config.json`:

```json
{
  "supabase_url": "https://<project>.supabase.co",
  "access_token": "<jwt>",
  "refresh_token": "<token>",
  "expires_at": 1733600000,
  "email": "user@example.com"
}
```

New module `gigaflow/_auth.py` owns read/write/refresh of this file. It must
create the file with `0600` and never log token values.

### New commands

- **`gigaflow login`** — prompt for email and a hidden password
  (`_fmt.prompt_password`), POST to
  `{supabase_url}/auth/v1/token?grant_type=password` with the anon key as the
  `apikey` header, store the returned `access_token` / `refresh_token` /
  `expires_in` (→ `expires_at`) and `email`. On 400 (bad creds), print a clear
  message pointing to the signup URL.
- **`gigaflow logout`** — delete `credentials.json`.
- **`gigaflow whoami`** — print the signed-in email (or "not signed in").

### First-run gate

A helper (e.g. `_auth.require_login(base_url)`) called by backend-touching
commands. If no credentials and no static `--api-key`/env override:

```
You're not signed in.
Sign up at https://api.gigaflow.io, then run:  gigaflow login
```

…and open the browser to the signup page (`webbrowser.open`). Bypassable by the
existing static `--api-key` / `GIGAFLOW_API_KEY` env (self-host/dev).

### Token handling

`gigaflow/_http.py` `api()` and the raw gzip POST in
`gigaflow/commands/supplement.py` send `Authorization: Bearer <access_token>`.

A refresh helper in `_auth.py`:
- If `expires_at` is in the past (with a small skew margin), refresh first.
- On a `401` response, refresh once and retry the request a single time.
- Refresh = POST `{supabase_url}/auth/v1/token?grant_type=refresh_token` with the
  stored `refresh_token`; persist the rotated tokens. On refresh failure, clear
  credentials and tell the user to `gigaflow login` again.

### Credential precedence

Explicit `--api-key` > user access token (from `credentials.json`) > static
`api_key` from `config.json`/env. Keeps self-host/dev working unchanged.

### Supabase URL + anon key delivery

The CLI learns the Supabase URL + anon key from a new public backend endpoint
`GET /api/v1/auth/config` → `{ "supabase_url": "...", "supabase_anon_key": "..." }`.
Cached in `credentials.json` after first fetch. Avoids hardcoding and lets
self-hosters repoint.

---

## Component 2 — Backend (`gigaflow`)

### Schema

- Add `Project.user_id` — owner `UUID(as_uuid=True)`, nullable, indexed.
- Alembic migration for the new column + index.
- Continue stamping `Trace.user_id` at ingest, **denormalized from the project
  owner**, so existing trace-level filters keep working.

### Auth gate swap

Move the customer-facing routers (projects, traces, spans, query, datasources,
supplement, sync, flow) from the static-key-only `require_flow_compute_auth` to
the existing either-or `get_current_user`:

- Supabase JWT → `user_id`
- static `FLOW_COMPUTE_API_KEY` → `None` (dev/self-host)
- `GIGAFLOW_DEV_MODE=true` → `None`

`/api/v1/health` stays public (ALB health check). `/api/v1/auth/config` is new
and public.

### Write scoping

- `create_project` stamps `user_id = current_user` (when present).
- Supplement / sync / OTLP ingest resolve the owner from the **target project**
  and stamp `Trace.user_id` accordingly.
- OTLP tokens already belong to a project, so owner flows through with no token
  changes.

### Read scoping

When a user identity is present, `list_projects` / `list_traces` / `get_project`
/ `get_trace` / `get_trace_spans` (and the other reads) filter to projects the
user owns; other users' resources 404 or return empty. The static service caller
(`None`, dev/self-host) remains unscoped (sees all) — that is the trusted
internal credential.

### New endpoint

`GET /api/v1/auth/config` (public) → `{supabase_url, supabase_anon_key}` sourced
from backend settings.

---

## Component 3 — Website (`gigaflow-website`)

- Swap `AuthContext` + `SignupDialog` from magic-link OTP to **email + password**
  (`supabase.auth.signUp` / `signInWithPassword`). Add a "forgot password" link
  (Supabase reset email).
- The trace/project list views already carry the user JWT — point them at the
  now-user-scoped read endpoints so users see only their own data.

---

## Component 4 — Supabase project config

- Enable the email/password provider + email confirmation.
- No backend JWT-verification changes — `supabase_auth.py` already handles the
  current signing scheme.

---

## Data flow (happy path)

```
pip install gigaflow
  → gigaflow supplement --latest
      → no credentials → prints signup URL, opens browser
  → (user signs up at api.gigaflow.io, confirms email)
  → gigaflow login        → password grant → credentials.json (0600)
  → gigaflow supplement --latest
      → GET /auth/config (if needed)
      → Bearer <access_token>
      → backend get_current_user → user_id
      → project resolved/created with user_id owner
      → Trace.user_id stamped
  → user opens api.gigaflow.io, logs in (same account)
      → list_traces filtered by owner → sees exactly their traces
```

## Testing strategy

- **SDK:** unit tests for `_auth` (store/load/refresh, `0600` perms, precedence
  order), `login`/`logout`/`whoami` command tests with a mocked Supabase token
  endpoint, and a 401→refresh→retry test in the HTTP path.
- **Backend:** migration test; `create_project` owner stamping; ingest
  (supplement/sync/OTLP) owner inheritance; read-scoping tests (user A cannot see
  user B's projects/traces; service key sees all; dev-mode unscoped); the new
  `auth/config` endpoint.
- **Website:** AuthContext password sign-up/sign-in unit tests; list views call
  the user-scoped endpoints.

## Open flags raised at design time (all accepted)

- (a) Making read endpoints user-scoped touches every list/get route — **in scope.**
- (b) Static service key stays as a dev/self-host fallback — **kept.**
- (c) `auth/config` endpoint ships the Supabase URL/anon-key to the CLI — **approved.**
