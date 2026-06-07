# Per-user accounts for the gigaflow CLI

**Date:** 2026-06-07
**Status:** Approved (design)
**Scope:** cross-repo — `gigaflow-sdk` (CLI), `gigaflow` (backend), `gigaflow-website` (UI), plus Supabase project config.

## Goal

Give the CLI a real per-user identity so that:

1. `pip install gigaflow`
2. `gigaflow login` opens api.gigaflow.io in the browser.
3. The user signs up **or** signs in there (email + password); on success the
   browser hands the session back to the CLI automatically — no password is ever
   typed in the terminal.
4. Credentials are stored locally, automatically.
5. Every trace the CLI uploads is **owned by that account**.
6. Logging into the web UI as the same account shows exactly those traces.

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
| Website login credential | **Email + password** | Supabase supports it natively; replaces magic-link OTP in the website UX. |
| CLI login mechanism | **Browser loopback handoff** | `gigaflow login` opens a hosted `/cli-auth` page; after the user signs in there, the browser POSTs the Supabase session back to a one-shot localhost callback. No password typed in the terminal; signup and signin share one page. (Trade-off: needs the hosted page + local server, and degrades on headless/SSH — see fallback below.) |
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

- **`gigaflow login`** — browser loopback handoff (no terminal password):
  1. Bind a one-shot HTTP server on a random `127.0.0.1:<port>` and generate a
     random `state` nonce.
  2. Open the browser to the hosted handoff page:
     `https://api.gigaflow.io/cli-auth?port=<port>&state=<state>`
     (print the URL too, in case the browser can't open).
  3. Wait (bounded timeout, e.g. 120 s) for the page to POST the Supabase
     session — `access_token`, `refresh_token`, `expires_in`, `email`, and the
     echoed `state` — to `http://127.0.0.1:<port>/callback`.
  4. Verify the returned `state` matches; reject otherwise. Store the tokens in
     `credentials.json`, respond to the browser with a "you can close this tab"
     success page, shut the server down.
  - `--no-browser` (or browser-open failure) prints the URL for manual paste.
    On a headless box where no browser is reachable, login can't complete this
    way — the static `--api-key`/env path remains for that case.
- **`gigaflow logout`** — delete `credentials.json`.
- **`gigaflow whoami`** — print the signed-in email (or "not signed in").

### First-run gate

A helper (e.g. `_auth.require_login(base_url)`) called by backend-touching
commands. If no credentials and no static `--api-key`/env override:

```
You're not signed in. Run:  gigaflow login
(opens api.gigaflow.io to sign up or sign in)
```

Bypassable by the existing static `--api-key` / `GIGAFLOW_API_KEY` env
(self-host/dev / headless).

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
- **New `/cli-auth` route** — the browser handoff page for `gigaflow login`:
  - Reads `port` + `state` from the query string.
  - If the user isn't signed in, renders the email+password sign-in / sign-up
    form (reusing `AuthContext`); after auth it continues automatically.
  - Once a Supabase session exists, POSTs `{access_token, refresh_token,
    expires_in, email, state}` to `http://127.0.0.1:<port>/callback`, then shows
    a "Return to your terminal — you're signed in" confirmation.
  - Only ever targets `127.0.0.1:<port>` (loopback); echoes back the `state` the
    CLI generated so the CLI can verify the round-trip.
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
  → gigaflow login
      → CLI binds 127.0.0.1:<port>, makes a state nonce, opens browser:
        https://api.gigaflow.io/cli-auth?port=<port>&state=<state>
      → user signs up or signs in (email+password) on the page
      → page POSTs {access_token, refresh_token, expires_in, email, state}
        to http://127.0.0.1:<port>/callback
      → CLI verifies state → credentials.json (0600) → "you can close this tab"
  → gigaflow supplement --latest
      → GET /auth/config (if Supabase url/anon key not cached, for refresh)
      → Bearer <access_token>  (refreshed via refresh_token when expired)
      → backend get_current_user → user_id
      → project resolved/created with user_id owner
      → Trace.user_id stamped
  → user opens api.gigaflow.io, signs in (same account)
      → list_traces filtered by owner → sees exactly their traces
```

## Security notes (loopback login)

- **Loopback only:** the callback server binds `127.0.0.1` (not `0.0.0.0`) on a
  random port, accepts a single request, then shuts down.
- **State nonce:** the CLI generates a random `state`, passes it to the page, and
  rejects any callback whose `state` doesn't match — defeats CSRF / a stray
  request hitting the port.
- **Bounded wait:** the server times out (~120 s) if no callback arrives.
- **Tokens never transit a third party:** the page talks directly to localhost;
  tokens are not placed in a redirect URL/query that could land in browser
  history or server logs.

## Testing strategy

- **SDK:** unit tests for `_auth` (store/load/refresh, `0600` perms, precedence
  order); `login` loopback flow with a simulated callback POST (state match +
  mismatch, timeout); `logout`/`whoami`; a 401→refresh→retry test in the HTTP
  path.
- **Backend:** migration test; `create_project` owner stamping; ingest
  (supplement/sync/OTLP) owner inheritance; read-scoping tests (user A cannot see
  user B's projects/traces; service key sees all; dev-mode unscoped); the new
  `auth/config` endpoint.
- **Website:** AuthContext password sign-up/sign-in unit tests; `/cli-auth` page
  delivers the session to the loopback callback and echoes `state`; list views
  call the user-scoped endpoints.

## Open flags raised at design time (all accepted)

- (a) Making read endpoints user-scoped touches every list/get route — **in scope.**
- (b) Static service key stays as a dev/self-host fallback — **kept.**
- (c) `auth/config` endpoint ships the Supabase URL/anon-key to the CLI — **approved.**
