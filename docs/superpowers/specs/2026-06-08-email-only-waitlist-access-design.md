# Email-only waitlist access — design

**Date:** 2026-06-08
**Status:** Approved (ready for implementation planning)
**Repos:** `gigaflow` (backend), `gigaflow-sdk` (CLI), `gigaflow-website` (marketing SPA)

## Context

We set out to reduce new-user friction in the GigaFlow CLI. Three problems were
raised:

1. The CLI fixates on Arize Phoenix despite being vendor-neutral.
2. Signup is broken — clicking "Sign up" never says "check your email," and
   confirming the email still doesn't let you log in.
3. A brand-new user has no idea where to start; there's no concept-level
   onboarding.

Diagnosis of #2 found the root cause in `gigaflow-website` (Supabase
`signUp`/`signInWithPassword` via `CliAuth.tsx` + `AuthContext.tsx`): the signup
response is never inspected for the email-confirmation state, and `CliAuth`
checks the session only once on mount so it never resumes the CLI handoff after
confirmation. The CLI side compounds this with a single-shot 120 s browser
loopback (`_auth.run_loopback_login`).

Rather than repair that fragile, multi-system flow, the product decision is to
**replace it with a much simpler email-only waitlist model**, and to gate access
**manually**.

This document specifies that waitlist model (the replacement for friction #2).
**Vendor-neutrality (#1) and concept onboarding (#3) are a separate spec**
("CLI vendor-neutral onboarding") to be brainstormed in its own cycle.

## Goals

- Joining the waitlist requires only an **email** — no password, no email
  confirmation, no Supabase.
- The operator (James) **manually allowlists** the emails allowed in.
- An allowlisted user authenticates the CLI by **typing their email** — the
  backend issues a token if the email is allowed.
- A not-yet-allowed user is pointed to the **book-a-demo modal** on gigaflow.io
  to join the waitlist.
- Consolidate to **one** auth system; delete the broken Supabase customer-auth
  path and the CLI browser loopback.

## Non-goals

- Passwords, email verification, magic links, OAuth/SSO.
- Per-request approval gating (the gate is at login only).
- Automatic promotion of leads to the allowlist (promotion is manual).
- Vendor-neutral onboarding / concept teaching (separate spec).
- Local dev / self-host behavior — `GIGAFLOW_DEV_MODE` continues to bypass auth
  unchanged.

## Accepted trade-off

Email-only login means **anyone who knows an allowlisted email can log in** —
the email is unverified. This is acceptable for a small, trusted, manually
curated beta. Revisit (magic link / verification) before broadening access.

## Architecture overview

```
                          gigaflow.io (website)
  visitor ──"Book a demo" modal (SignupDialog → /api/lead, Cloudflare fn)──▶ lead notification (email)
                                                                                   │
                                                              operator reviews leads, manually
                                                              inserts row in allowlisted_emails
                                                                                   │
                                                                                   ▼
  user ──`gigaflow login` (Waitlist email: …)──▶ POST /api/v1/auth/login {email}
                                                     │
                              ┌──────────────────────┴───────────────────────┐
                       email in allowlist                            email NOT in allowlist
                              │                                               │
                  find-or-create users row,                       403 {code:"not_on_allowlist"}
                  issue existing session JWT  ◀── token ──▶ CLI       │
                  (CLI stores in credentials.json)                    ▼
                                                          CLI prints + opens browser:
                                                          "Want to join the waitlist? Book a demo:
                                                           https://gigaflow.io/?book-demo"
```

The waitlist funnel (lead capture) **already exists** and is unchanged except
for a deep-link to auto-open the modal. Leads are captured by the existing
`/api/lead` Cloudflare Pages function and do **not** flow into the backend
automatically — the operator copies allowed emails into the allowlist by hand.

## Component 1 — Backend (`gigaflow`)

### Data model
- New table `allowlisted_emails`:
  - `email` (citext, primary key / unique) — reuses the citext extension already
    added in migration `0003`.
  - `added_at` (timestamptz, default now).
- Alembic migration `0005_allowlisted_emails.py`.
- The operator grants access by inserting a row:
  `INSERT INTO allowlisted_emails (email) VALUES ('person@company.com');`
  (A tiny admin helper endpoint is optional and out of scope for v1 — a
  documented SQL one-liner is sufficient for "manually turn it on.")

### Login endpoint
- Rework `POST /api/v1/auth/login` (in `backend/app/api/routers/auth.py`) to
  accept `{ "email": "<addr>" }` (no password).
- Behavior:
  1. Normalize/validate the email.
  2. Look up `allowlisted_emails`. If **absent** → `403` with body
     `{ "code": "not_on_allowlist", "book_a_demo_url": "<site>/?book-demo" }`.
  3. If **present** → find-or-create a row in the existing `users` table keyed by
     email (no password; `password_hash` becomes nullable, `is_active=true`),
     update `last_login_at`, and issue the existing HS256 session JWT via
     `user_auth.issue_session_jwt()` (sub = `users.id`). Return
     `{ "access_token": "<jwt>", "email": "<addr>", "expires_in": 86400 }`.
- Reusing the existing JWT + `get_current_user` machinery means **no new
  per-request gate** and existing per-user ownership scoping (`trace.user_id`,
  `project.user_id`) keeps working. Issuing the token *is* the gate.

### New endpoint
- `GET /api/v1/auth/me` → `{ "email": "<addr>" }` for the authenticated caller
  (used by `gigaflow whoami`).

### Schema/model changes
- `backend/app/models/user.py`: make `password_hash` nullable.
- `backend/app/api/deps/user_auth.py`: `signup`/password-login paths are removed
  or left dormant; the session-JWT verification (`verify_session_token`) and
  `get_current_user` are unchanged.

### Retire
- The Supabase customer-auth pathway is no longer used by the website or CLI.
  Backend Supabase JWT verification (`supabase_auth._verify_supabase_jwt`) may
  remain for any internal callers but is not part of the customer login flow.
  (Removal of dead Supabase config is a cleanup, not load-bearing.)

## Component 2 — CLI (`gigaflow-sdk`)

### `gigaflow login` (rewrite `_auth.py` + `commands/auth.py`)
- Prompt, labeled exactly **`Waitlist email:`**.
- `POST {base_url}/auth/login {email}`.
- On success: store `{ "access_token", "email", "expires_at" }` in
  `~/.gigaflow/credentials.json` (0600).
- On `403 not_on_allowlist`: print
  `Want to join the waitlist? Book a demo: https://gigaflow.io/?book-demo`
  and `webbrowser.open(...)` that URL.
- No browser loopback, no password, no Supabase config fetch.

### Token handling (`_auth.access_token()`)
- Return the stored token until `expires_at`. On expiry, return `None` and let
  the "not signed in — run `gigaflow login`" path prompt a fresh login. Backend
  issues a new 24 h token each login; there is **no** refresh token.

### Other commands
- `whoami` → call `GET /auth/me` (or read stored email) and print it; "Not
  signed in" otherwise.
- `logout` → unchanged (`clear_credentials`).

### Delete
- `_auth.run_loopback_login`, `_web_base`, `_fetch_auth_config` (Supabase),
  `_supabase_refresh`, and the loopback HTTP server.
- The site/Supabase fields persisted in `credentials.json` (`supabase_url`,
  `anon_key`, `refresh_token`) — drop on next login.

### Friendly errors (`_http.py`)
- Add a hint for the `not_on_allowlist` 403 mirroring `auth_error_hint()`.

## Component 3 — Website (`gigaflow-website`)

### Deep-link to the book-a-demo modal
- Support the `?book-demo` query param (the exact URL the CLI links to:
  `https://gigaflow.io/?book-demo`) that auto-opens the existing `SignupDialog`
  via `SignupContext` on load.

### Copy
- Optionally relabel the dialog/CTA toward "waitlist" language (currently titled
  "Book a demo" / success "You're on the list"). Cosmetic; keep if preferred.

### Retire
- Remove (or stop routing to) the Supabase `CliAuth.tsx` signup/login handoff
  and the Supabase calls in `AuthContext.tsx` — now unused. The `/cli-auth`
  route can be deleted.

## Implementation order

1. **Backend** — migration + login rewrite + `/auth/me` (+ make
   `password_hash` nullable). Merge first (CLI is a thin client).
2. **CLI** — new email-only `login`, delete loopback, `whoami`, friendly 403.
3. **Website** — deep-link to modal; retire `CliAuth`.

Each repo gets its own branch + PR (per repo policy). Backend PR merges before
the CLI PR.

## Risks / to confirm during build

- **Backend native auth must be live on hosted `api.gigaflow.io`**
  (`AUTH_JWT_SECRET` configured in prod). Load-bearing assumption.
- **Existing logged-in CLI users re-login once** after the switch. Acceptable at
  v0.3.x.
- **Operator must maintain the allowlist by hand**; leads from `/api/lead` are
  notifications only, not auto-promoted.
- The website deep-link assumes `SignupContext`/`SignupDialog` can be opened
  programmatically from a route/param (it exposes `setOpen` — confirmed).

## Out of scope (tracked separately)

- **Spec 2: CLI vendor-neutral onboarding** — replace Arize-specific defaults
  and copy with a source-picker wizard (Arize / Logfire / Claude Code / OTLP)
  and add concept-level first-run guidance. Addresses friction #1 and #3.
