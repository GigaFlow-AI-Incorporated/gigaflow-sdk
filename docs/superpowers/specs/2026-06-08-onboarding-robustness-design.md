# Onboarding robustness & polish — design

**Date:** 2026-06-08
**Status:** Draft (pre-authorized for implementation via `/goal`)
**Repo:** `gigaflow-sdk` (CLI), plus small fixes in `gigaflow` (examples + docs/backend)
**Builds on:** PR #9 `spec/multi-vendor-setup-wizard` (multi-vendor `setup`, bundled
`braintrust.yml`/`mlflow.yml`/`wb_weave.yml`, doc rewrites). This branch is stacked
on that one.

## Problem

A new-user e2e walkthrough (Braintrust trace → hosted backend `api.gigaflow.io`,
freshly `pip install`ed `gigaflow` 0.3.1) surfaced friction that PR #9 does **not**
address. With #9, a Braintrust user can finally `gigaflow setup` and `sync`. But:

- **Blocker — `gigaflow compute` lies about failure on the hosted backend.** The
  synchronous `POST /flow/{trace_id}` exceeds the hosted gateway's ~60s cap →
  **HTTP 504**, and the CLI's own 30s read timeout fires even earlier →
  `_run_one` raises `unreachable_hint` ("Could not reach the gigaflow backend").
  Yet the backend keeps working and the run lands minutes later. The user sees a
  hard failure; a naive retry spawns a **duplicate run** (observed 3 runs / 3×
  cost for one trace).
- **Medium — read-after-write lag.** Immediately after `sync`/`compute`, by-id
  `GET /traces/{id}` and `/traces/{id}/spans` return **404** ("Trace not found")
  for a minute or two, then self-heal — so `gigaflow inspect` (the payoff
  command) fails right when the user runs it in sequence.
- **Stale hint.** `gigaflow traces` prints `Run Flow: gigaflow run flow <id>` —
  there is no `run` command; it is `gigaflow compute`.
- **`.env` clobber.** `examples/braintrust/.env(.example)` ships an empty
  `OPENAI_API_KEY=` that silently overrides a real key when sourced; `compute`
  then dies with "OPENAI_API_KEY not set."
- **Polish.** No `gigaflow --version`; top-level `--help` still says "ingest
  Arize Phoenix traces"; `compute` hard-requires a client `OPENAI_API_KEY` even
  on hosted where the README says Flow runs on GigaFlow's platform key; docs
  reference an `intent_fulfillment` column absent from `trace_metrics`; the
  datasource GET echoes `api_key` in plaintext.

## Goals

The documented happy path —
`gigaflow setup` → `gigaflow compute` → `gigaflow inspect <id>` — completes for a
Braintrust user on the **default hosted backend** with **no command that reports
a false failure** and **no duplicate runs**, ending at a rendered Flow viewer.

## Non-goals

- A backend **async compute** API (job id + status polling). The client-side
  poll-after-timeout below makes the existing synchronous endpoint usable behind
  the gateway; a true async API is a tracked follow-up, not required here.
- Raising the hosted gateway timeout (infra; tracked separately).
- New vendor transforms beyond #9.

## Design

All CLI changes live in `gigaflow-sdk`; they are additive and self-contained.

### 1. Robust `compute` (poll-after-timeout) — `commands/compute.py`, `_http.py`

- Give the compute `POST /flow/{trace_id}` its own longer timeout
  (`COMPUTE_TIMEOUT`, default **180s**, overridable via `--timeout N` and
  `$GIGAFLOW_COMPUTE_TIMEOUT`) so the client does not bail at 30s before the
  gateway even responds.
- In `_run_one`, treat **`status is None` (timeout)** and **`status in {502,503,
  504}` (gateway)** as *"server still working"*, not failure: enter
  `_poll_for_run(base_url, trace_id, key, deadline)` which polls the `/query/`
  view
  `SELECT run_id, groundedness, tool_consumption, total_cost_usd FROM
  trace_metrics WHERE trace_id = '<id>' AND run_id IS NOT NULL`
  every few seconds until the run appears or a deadline (default 300s) elapses.
  On success, return the metrics exactly as the 200 path would. On deadline,
  raise a clear "still computing after Ns — re-run `gigaflow compute` later to
  pick up results" message (NOT "unreachable").
- Because a 504/timeout now **polls instead of re-POSTing**, no duplicate run is
  created. A genuine connection refusal (DNS/connect error, distinct from a
  timeout) still surfaces `unreachable_hint`.
- `_http.api` already distinguishes connect failure from HTTP responses; add a
  way for callers to tell "timeout" (`status is None` + reason mentions timeout)
  from "connection refused". Minimal approach: return the reason string in the
  payload (already does) and have compute check it; keep the public contract.

### 2. Read-after-write retry — `commands/inspect.py`, `commands/traces.py`

- Add a shared helper `_get_with_retry(base_url, path, api_key, tries=5,
  delay=2.0)` that issues the GET and, **only on 404**, retries with short
  backoff before giving up (covers eventual-consistency right after sync/compute).
  Use it for by-id `GET /traces/{id}` and `GET /traces/{id}/spans` in `inspect`
  and `spans`. Non-404 errors fail fast as today.

### 3. Small CLI fixes

- `commands/traces.py`: change the hint `gigaflow run flow <id>` →
  `gigaflow compute "...<id>..."` (point at the real command).
- `cli.py`: add top-level `--version` (read `importlib.metadata.version
  ("gigaflow")`); update the parser description from "ingest Arize Phoenix
  traces" to vendor-neutral wording (verify #9 hasn't already).
- `commands/compute.py`: make `OPENAI_API_KEY` **optional**. If unset, omit it
  from the request body and print an info line ("no OPENAI_API_KEY set — the
  hosted backend will use its platform key"); only surface an actionable error
  if the backend itself rejects the request for a missing key. Matches the
  README's hosted-key claim.

### 4. `gigaflow` repo (separate worktree + PR)

- `examples/braintrust/.env.example` (and any sibling templates with the same
  issue): remove/comment the bare `OPENAI_API_KEY=` so sourcing never clobbers a
  real key.
- `QUERYING.md` / README: replace the `intent_fulfillment` column reference with
  a column that actually exists in `trace_metrics` (verify against the view).
- Backend `api_key` redaction in datasource GET responses: assess in the
  datasources router/schema; implement only if low-risk (exclude from the
  response model), else file a GitHub issue. Lower priority.

## Testing

- Unit (stdlib `unittest`/pytest, mock `api()`):
  - compute returns success when the POST times out (`status None`) but
    `trace_metrics` subsequently reports a `run_id` (poll path); asserts **one**
    POST is issued (no duplicate run).
  - compute polls on 504 identically.
  - compute deadline path raises the "still computing" message, not
    "unreachable".
  - genuine connection refusal still raises `unreachable_hint`.
  - `inspect`/`spans` succeed when the first by-id GET 404s then a retry 200s.
  - `compute` proceeds with no `OPENAI_API_KEY` (body omits the key).
  - `traces` hint string contains `gigaflow compute`, not `run flow`.
  - `--version` prints the package version.
- E2E + UI (Playwright agent, real hosted backend): `gigaflow setup` (braintrust)
  → `gigaflow compute` → `gigaflow inspect <id>`; open the viewer URL in a
  browser, assert the Flow result renders (the fabricated **Embarcadero**
  Hallucinated atom at rank 1), screenshot.

## Rollout

Two PRs: this branch (CLI robustness, stacked on PR #9) and a `gigaflow`-repo PR
(examples/docs/backend-redaction). Land #9 first, then this.
