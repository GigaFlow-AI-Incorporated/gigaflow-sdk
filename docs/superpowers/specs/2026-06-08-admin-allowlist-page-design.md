# Admin allowlist page (shared-token) — design

**Date:** 2026-06-08
**Status:** Approved (ready for implementation planning)
**Repos:** `gigaflow` (backend), `gigaflow-website` (marketing SPA)
**Builds on:** [email-only waitlist access](2026-06-08-email-only-waitlist-access-design.md) — reuses the `allowlisted_emails` table.

## Context

Email-only waitlist access shipped: the backend gates `POST /api/v1/auth/login`
on an `allowlisted_emails` table, and the operator grants access by inserting
rows. Today that insert is **raw SQL against the prod DB** — the operator wants
a way to manage authorized emails **without touching the DB directly** and
**without using the customer-facing `gigaflow` CLI**.

This spec adds an **internal admin surface**: a protected `/admin` page on
gigaflow.io backed by an admin-gated backend API, authenticated with a **shared
admin token**.

## Goals

- List / add / remove allowlisted emails from a web page, no SQL, no customer CLI.
- Gate the admin API with a single shared secret (`GIGAFLOW_ADMIN_TOKEN`).
- Reuse the existing `allowlisted_emails` table — no schema change.

## Non-goals

- Per-user admin accounts, roles, or audit trail (shared token only).
- Supabase or any other auth provider for admin (token only).
- Managing leads (those remain Resend emails to `founders@gigaflow.io`).
- Revoking already-issued session JWTs (removal stops *new* logins only).

## Accepted trade-offs

- **Shared secret**: anyone with the token can manage the allowlist; no record
  of *which* admin made a change. Acceptable for a small founding team. Rotated
  by changing the env var (and re-entering it in the page).
- **Token in the browser**: stored in `localStorage` so it persists across
  visits. An XSS on gigaflow.io could read it; blast radius is limited to
  allowlist add/remove (no customer data). A "Forget token" button clears it.

## Architecture

```
operator ──▶ gigaflow.io/admin  (token in localStorage)
                │  fetch /api/admin/*  + Authorization: Bearer <GIGAFLOW_ADMIN_TOKEN>
                ▼
   Cloudflare Pages Function  functions/api/admin/[[path]]   (same-origin, no CORS)
                │  forwards the bearer header to GIGAFLOW_BACKEND_URL
                ▼
   api.gigaflow.io  /api/v1/admin/allowlist   [require_admin gate]
                │
                ▼
        allowlisted_emails  (existing table)
```

Two pieces, mirroring the waitlist feature's backend/website split.

**Transport (refinement during planning):** the browser calls a **same-origin
Cloudflare Pages Function proxy** (`/api/admin/*`), which forwards the operator's
bearer token to the backend — mirroring `functions/api/analyze.ts`. This matches
the site's established pattern, keeps the backend origin hidden, and avoids
relying on CORS. Same token model (operator enters the token; the browser sends
it as `Authorization: Bearer`; the function forwards it verbatim).

## Component 1 — Backend (`gigaflow`)

### Config
- New setting in `backend/app/core/config.py`: `GIGAFLOW_ADMIN_TOKEN: str | None = None`.

### Admin gate
- New dependency `require_admin` (in a new `backend/app/api/deps/admin_auth.py`):
  - Reads the bearer token from `Authorization: Bearer <token>`.
  - **Fail-closed**: if `settings.GIGAFLOW_ADMIN_TOKEN` is unset → `503`
    ("admin API not configured"); missing/malformed/mismatched token → `401`.
  - Constant-time compare (`hmac.compare_digest`).
  - In `GIGAFLOW_DEV_MODE`, if the token is unset, allow (consistent with the
    other dev-mode bypasses) — so local dev works without configuring a secret.

### Router
- New `backend/app/api/routers/admin.py`, mounted under `/api/v1/admin` **outside**
  the customer-auth gate (`_customer_api_deps`) — like `auth`/`web_ingest` — with
  `dependencies=[Depends(require_admin)]` on the router so every route is gated.
  - `GET /admin/allowlist` → `{"emails": [{"email", "added_at"}]}` ordered by `added_at`.
  - `POST /admin/allowlist` body `{"email": "<addr>"}` → validate (`EmailStr`),
    `INSERT … ON CONFLICT (email) DO NOTHING`, return `{"email", "added": bool}`.
  - `DELETE /admin/allowlist/{email}` → delete the row, return `{"email", "removed": bool}`.
- Reuses the `AllowlistedEmail` model. Uses `get_traces_db` for the session.

### Transport
- `Authorization: Bearer <token>` (reuses existing CORS allow-list for the
  `Authorization` header — no new allowed-header needed).

## Component 2 — Website (`gigaflow-website`)

### Route
- `/admin` handled by a pathname early-return in `src/App.tsx` (the same pattern
  the retired `/cli-auth` route used — no router library). Renders a new
  `src/components/AdminAllowlist.tsx`. No `AuthProvider`/Supabase needed.

### Page behavior (`AdminAllowlist.tsx`)
- On load, read the token from `localStorage` (`gigaflow_admin_token`). If absent,
  show a token-entry field. On entry, store it and load the list.
  (All calls go to the same-origin proxy `/api/admin/*`, which forwards to the
  backend's `/api/v1/admin/*`.)
- **List**: `GET /api/admin/allowlist` with the bearer header → render a table
  of `email` + `added_at`, each row with a **Remove** button.
- **Add**: an email input + button → `POST /api/admin/allowlist {email}` →
  refresh the list. Basic client-side email-format check before sending.
- **Remove**: `DELETE /api/admin/allowlist/{email}` → refresh the list.
- **401 handling**: show an "invalid or missing admin token" state and re-prompt
  for the token (clear the stored one).
- **Forget token** button: clears `localStorage` and returns to the entry state.
- Backend origin: hidden behind the Pages Function proxy (`GIGAFLOW_BACKEND_URL`,
  already configured for `functions/api/analyze.ts`); the browser only ever hits
  same-origin `/api/admin/*`.

## Error handling

- Backend: `503` (unset token) and `401` (bad token) from `require_admin`; `422`
  on an invalid email (`EmailStr`); idempotent add/remove (`ON CONFLICT DO
  NOTHING` / delete-if-exists) so repeats are safe.
- Website: network/`5xx` → inline error message with retry; `401` → token
  re-prompt; optimistic-free (always re-fetch the list after a mutation).

## Testing

- **Backend** (`tests/api/deps/test_admin_auth.py`, `tests/api/test_admin_allowlist.py`):
  - `require_admin`: valid token → pass; missing/wrong → 401; unset env (prod) →
    503; unset env (dev mode) → pass.
  - Endpoints (mocked DB): list returns rows; add inserts + is idempotent;
    delete removes; all reject without a valid token.
- **Website** (`src/components/AdminAllowlist.test.tsx`, vitest + jsdom):
  - No token → entry field shown; entering a token loads the list (fetch mocked).
  - Add calls `POST` then re-fetches; remove calls `DELETE` then re-fetches.
  - `401` → re-prompt state.

## Rollout

1. **Backend first** — merge, then set `GIGAFLOW_ADMIN_TOKEN` in the prod backend
   environment (the page is unusable until this is set; `require_admin` returns
   503 without it).
2. **Website** — merge; the `/admin` page calls the live API.
3. Operator opens `gigaflow.io/admin`, pastes the token once, manages the list.

One spec, two implementation phases (backend → website), each its own per-repo
branch + PR. Backend merges first (the website calls it).

## Open risks / to confirm during build

- The prod backend env must have `GIGAFLOW_ADMIN_TOKEN` set (delivered out of
  band, not committed). Without it the admin API is 503 (fail-closed) — correct,
  but the page won't work until set.
- Confirm the website's existing backend-base-URL resolution is reachable from
  the `/admin` page (it bypasses the normal providers via the early-return).
