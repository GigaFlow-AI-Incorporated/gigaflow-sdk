# `gigaflow setup` Onboarding Friction Fixes — Design

**Date:** 2026-06-08
**Status:** Approved (pending spec review)
**Scope:** `gigaflow-sdk` CLI `setup` wizard, auth wiring, and supporting docs.

## Problem

First-time users hit avoidable friction running `gigaflow setup`:

1. The wizard's first prompt asks for a "path to gigaflow.env" with no explanation
   of what that file is or how to create one. It's a dev convenience exposed as a
   required-looking step.
2. The wizard prompts for the backend base URL. End users have no reason to change
   it; only devs running a local backend do.
3. The wizard prompts for an API key. Users don't have one and don't know where to
   get it, even though a working browser login flow already exists.
4. The project-name prompt silently defaults to a vendor-derived value
   (e.g. `arize_phoenix-project`) without explaining what a "project" is.

A fifth item surfaced during design: vendor selection and per-vendor connection
collection already exist but should get the same explanatory polish as the rest.

## Current architecture (as-is)

- Entry: `gigaflow/cli.py` → `gigaflow/commands/setup.py` → `gigaflow/_setup.py:run_wizard()`.
- `run_wizard()` runs, in order: gigaflow.env path → backend URL + API key →
  vendor pick → vendor connection collector → project name → transform → register
  datasource + sync → save config (`~/.gigaflow/config.json`).
- Default backend `https://api.gigaflow.io/api/v1` is already defined in
  `cli.py` (`DEFAULT_BACKEND_URL`), with precedence
  `--backend > $GIGAFLOW_BACKEND_URL > saved config > default`.
- A complete browser loopback login (`gigaflow login`) lives in `gigaflow/_auth.py`
  (`run_loopback_login`), storing a JWT in `~/.gigaflow/credentials.json`. It is
  **not** currently invoked by `setup`.
- Project-name default: `conn.get("vendor_project_name") or
  env.get("GIGAFLOW_PROJECT_NAME") or f"{vendor.key}-project"` (`_setup.py:290`).
- Vendor pick: `_pick_vendor()` (`_setup.py:276`); per-vendor `collect_*`
  functions (`_setup.py:36-115`).
- `gigaflow.env` parsing: `load_env_file()` (`_setup.py:142`); auto-loaded from cwd
  at CLI startup (`cli.py:138`).

## Design

Incremental modification of the existing wizard. No rewrite.

### Step 1 — Input method choice (fixes #1)

Replace the bare `"Path to gigaflow.env (leave blank to enter values manually)"`
prompt with an explicit two-option choice:

```
How do you want to provide configuration?
  1) Enter values interactively (recommended)
  2) Load from a gigaflow.env file
See https://docs.gigaflow.io/gigaflow-env for the gigaflow.env format.
```

- Choice **1** (default): skip file loading; `env = {}`; prompt for everything.
- Choice **2**: prompt for the file path, `load_env_file()` it, use the values as
  defaults / to skip already-provided prompts (current behavior).
- The docs link points to a new page documenting every recognized field.

### Step 2 — Remove backend URL prompt (fixes #2)

Delete the `"Backend base URL"` prompt from the wizard. The wizard uses the
already-resolved backend URL (default `https://api.gigaflow.io/api/v1`). Devs
override silently via `--backend` / `$GIGAFLOW_BACKEND_URL` (unchanged mechanism).
When a non-default backend is in effect, print a one-line `Using backend: <url>`
notice so devs can confirm the override is active.

### Step 3 — Login-based auth, no API-key prompt (fixes #3)

Remove the `"GigaFlow API key"` prompt. Add a new helper
`ensure_authenticated(base_url)` (in `gigaflow/_auth.py`) used by `setup`:

1. If a dev API key is supplied (`--api-key` or `$GIGAFLOW_API_KEY` /
   `$GIGAFLOW_FLOW_API_KEY`), use it and skip login.
2. Else if valid stored credentials exist (`credentials.json`, refreshing if
   needed), use them.
3. Else auto-trigger `run_loopback_login(base_url)`, then continue with the
   resulting token.

`gigaflow login` / `logout` / `whoami` remain as standalone commands for re-auth
and account switching. After this change, `gigaflow.env` no longer needs
`GIGAFLOW_API_KEY` — it becomes a dev-only override.

### Step 4 — Vendor selection polish (new item)

Keep the 5-vendor menu (`_pick_vendor()`). Add a short one-line description per
vendor and a docs link to the per-vendor setup guide already under `docs/sources/`.

### Step 5 — Vendor connection polish

Each `collect_*` function gains: a brief explanation per field, a per-vendor docs
link telling the user where to find those credentials, and clearer defaults. No
change to which fields are collected.

### Step 6 — Project name: explain + suggest (fixes #4)

Before the prompt, print one explanatory line:

> A project is a namespace that groups your traces and evals in GigaFlow.

Then prompt with an **editable, vendor-derived suggestion**:
- Use the vendor's own project name when it provides one (Braintrust, W&B Weave).
- Otherwise (Arize Phoenix, Logfire, MLflow) suggest `"default"`.
- `GIGAFLOW_PROJECT_NAME` from a loaded gigaflow.env still takes precedence as the
  pre-filled value.

Drop the silent `{vendor.key}-project` fallback.

### Steps 7-9 — unchanged

Transform config, datasource registration + sync + preview, and config save are
unchanged.

## Supporting changes

- **New docs page** `docs/gigaflow-env.md`: documents all recognized gigaflow.env
  fields, grouped as GigaFlow core (`GIGAFLOW_BACKEND_URL`,
  `GIGAFLOW_PROJECT_NAME`, `GIGAFLOW_TRANSFORM_YML`, dev-only `GIGAFLOW_API_KEY`,
  `OPENAI_API_KEY`) and per-vendor sections (Arize Phoenix DB vars, Braintrust,
  Logfire, MLflow, W&B Weave). Published at `docs.gigaflow.io/gigaflow-env`.
  Linked from the setup prompt and added to the docs nav/index.
- **New helper** `ensure_authenticated()` in `gigaflow/_auth.py`.
- **README / docs index** updated: setup is login-based (no API key); document the
  new first-step input-method choice.

## Testing

- Update `tests/test_setup_wizard_vendors.py` for the new flow: no backend-URL or
  API-key prompts; auth resolved via `ensure_authenticated` (mock login /
  credentials); project-name suggestion logic.
- New test for the Step 1 input-method branch (interactive vs file).
- New test for `ensure_authenticated()`: dev-key short-circuit, existing-credential
  path, and login-triggered path (mock `run_loopback_login`).
- Existing `test_load_env_file.py` and `test_auth_login.py` remain green.

## Out of scope

- No change to the transform, datasource, sync, or preview steps.
- No change to credential storage format or the login server itself.
- No bigger rework of vendor selection mechanics (polish only).

## Open decisions (resolved)

- Auth: auto-login in setup, **keep** standalone `login`/`logout`/`whoami`.
- Project name: explanation + editable vendor-derived suggestion (fallback
  `"default"`).
- Vendor flow: polish existing, no rework.
- Docs URL: `docs.gigaflow.io/gigaflow-env`.
