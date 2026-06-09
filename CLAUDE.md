# CLAUDE.md

## ⚠️ Worktree + branch policy (MANDATORY — read before any edit)

**The single most important rule in this repo.** Before making ANY code change,
you MUST be working on a NEW git worktree and a NEW branch. Never edit the main
checkout and never commit to `main`/`master` directly.

At the start of any task that will modify files:

1. **Create an isolated worktree first** — use the `EnterWorktree` tool (preferred),
   or `git worktree add .claude/worktrees/<name> -b <branch>`.
2. **Proactively suggest a branch name** derived from the task, kebab-case, with a
   conventional prefix: `feat/…`, `fix/…`, `chore/…`, `spec/…`, `docs/…`.
   Propose it up front — don't wait to be asked.
3. **Do all work in that worktree.** A global `PreToolUse` hook
   (`~/.claude/hooks/enforce-worktree.sh`) hard-blocks Edit/Write/NotebookEdit in
   the main checkout. Override only when you truly mean to: `GIGAFLOW_ALLOW_MAIN=1`.

Read-only work (searching, answering questions, inspecting) does not need a worktree.

## PR Ownership

When explicitly asked to own a PR through merge, keep monitoring review comments and CI. Address all actionable unresolved review threads, push fixes, rerun checks, and merge once CI is green, the branch is mergeable, and there are no unresolved requested changes. Stop and ask for user review before making or merging changes that are broad, risky, security-sensitive, data-destructive, migration-related, or likely to break existing behavior.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e .          # install CLI locally for development
uv run pytest             # run CLI tests
uv run ruff check .       # lint
```

## Local development cycle

The CLI is published as its own package (`gigaflow`) and used against a
running gigaflow backend. When a backend change (new endpoint, new field,
etc.) requires a matching CLI change, the loop looks like:

```bash
# One-time: editable install from the checkout
cd /path/to/gigaflow-cli
pip install -e .

# Point at a local backend via the normal setup flow
gigaflow setup                                 # enter http://localhost:8000 when prompted

# Iterate: edit source, rerun the command — no reinstall needed
$EDITOR gigaflow/commands/sync.py
gigaflow sync                                  # picks up your edits immediately
gigaflow query "select * from trace_metrics limit 5"
```

`pip install -e .` installs the `gigaflow` console script to your active
environment (venv / uv / system) with the source directory linked in, so
every edit is live on the next invocation. No rebuild, no reinstall.

**Coordinated change across repos:** when a single feature spans backend
and CLI, branch both repos, run the backend locally (`docker compose up`
in `gigaflow/`), and run the editable CLI against it. Merge the backend
PR first, then the CLI PR — the CLI is a thin HTTP client and defaults
to failing gracefully on missing endpoints.

**Publishing a release:** bump `version` in `pyproject.toml`, tag, and
push — `.github/workflows/publish.yml` handles the PyPI upload.

## Architecture

The CLI has **zero external dependencies** — stdlib only (`urllib`, `argparse`, `json`, `pathlib`, `concurrent.futures`). All HTTP calls to the backend use `urllib` directly.

**Config** is persisted in `~/.gigaflow/config.json` with keys `backend_url`, `project_id`, `datasource_id`, and `api_key` (the GigaFlow backend auth token). `_config.py` exposes `load/save/clear` plus `get(key, default)` / `set(key, value)` (the latter preserves the other keys). `gigaflow.env` in the working directory is auto-loaded at startup via `set -a && source gigaflow.env`.

**Backend URL & API key resolution** — both are resolved once in `cli.py`'s `main()` and threaded to handlers as `base_url` / `args.api_key`:

- **Backend URL**: `--backend <url>` > `$GIGAFLOW_BACKEND_URL` > config `backend_url` > `http://localhost:8000/api/v1`.
- **API key**: `--api-key <key>` > `$GIGAFLOW_API_KEY` > config `api_key` > `None`.

**Auth forwarding** — when an API key is resolved, `_http.api()` attaches it as `Authorization: Bearer <key>` on every request (harmless on unauthenticated endpoints; required by the backend's Flow compute endpoint when `GIGAFLOW_DEV_MODE=false`). `_http.api()` also applies a 30 s timeout and retries idempotent GET/HEAD/OPTIONS and connection errors up to three times with exponential backoff; HTTP error responses (4xx/5xx) are never retried so auth failures fail fast. The `(status, payload)` contract returns `status is None` on a connection-level failure (vs. the real HTTP code on an error response). `supplement.py` posts a raw gzip body outside the JSON helper and attaches the bearer header + timeout directly. Friendly hints live in `_http.auth_error_hint()` and `_http.unreachable_hint(base_url)`.

> **OpenAI key vs. GigaFlow key.** `compute.py` *additionally* sends the user's `OPENAI_API_KEY` in the request **body** (as `{"api_key": ...}`, a confusingly-named field that is the OpenAI key) for the backend's LLM calls. This is separate from the GigaFlow bearer token — do not conflate or remove either.

**Transform config resolution** — `gigaflow setup` prompts for a `transform.yml` path. If left blank, the built-in transform for the selected vendor (bundled as package data in `gigaflow/transforms/`) is used.

**Built-in transforms** — one per vendor ships as package data in `gigaflow/transforms/` (`arize_phoenix.yml`, `logfire.yml`, `braintrust.yml`, `mlflow.yml`, `wb_weave.yml`). Arize/Braintrust/MLflow classify on a structural span-type field; Logfire classifies on pydantic-ai span-name conventions (generic for pydantic-ai instrumentation); `wb_weave.yml` is a TEMPLATE (Weave has no structural span-type) that you'll likely tailor to your op names — the setup preview shows whether it matched.

**Key commands:**
- `ingest <file>` — minimal-friction path: upload a local OTel JSON export (OTLP envelope or flat span array, `-` for stdin) to `POST /api/v1/ingest/otel`, which auto-provisions a per-user project, detects the exporter, and runs Flow on a background task; the CLI polls `GET /api/v1/ingest/otel/status/{flow_run_id}` until complete (tolerating transient poll failures — the run continues server-side), then prints/opens the `/flow/{trace_id}` viewer link. `--exporter` overrides auto-detect; `--label` names the trace; `--no-wait` prints the link without polling; 422 rejections surface the backend's typed `{reason, message}` explanation.
- `setup` — interactive first-run: pick your tracing vendor (Arize Phoenix / Braintrust / Logfire / MLflow / W&B Weave), enter its connection, name a GigaFlow project (auto-suggested from your vendor project where available), then runs a **connection preflight** check against the backend before proceeding. If the preflight fails, an interactive retry loop lets you [r]etry, [e]dit connection details, or [q] save & quit. Choosing save & quit (or a successful preflight) always saves config and registers the datasource — even if the source isn't reachable yet — so `gigaflow sync` can be retried later without re-running setup. The sync and classification preview are skipped on save & quit. On a successful connection, the wizard continues: upload a built-in or custom transform, register the datasource, sync, and show a classification preview.
- `sync` — queries source Phoenix Postgres directly, batches raw spans, POSTs to `/api/v1/datasources/{id}/sync`; skips traces already in the DB. "No configuration found" no longer results from a failed first sync — setup always saves config; use `gigaflow sync` to retry after fixing source access. After a successful sync it prints direct `/flow/{trace_id}` viewer links for the newest synced traces (best-effort read-back of `/traces/`, capped at 5).
- `query "<SQL>"` — run a SQL SELECT against the `trace_metrics` view; use `--examples` to print suggested patterns; `--format table|csv|json`; `--file` to read SQL from a file
- `compute "<SQL>"` — batch-compute Flow for traces returned by a SQL query; the query must return `trace_id`; skips traces with existing results unless `--force`; `--concurrency N` (default 3); `--model`; `--k-threshold`; `--cost-breakdown` prints a per-stage (model, tokens, requests, USD) table after each run, in addition to the default one-line `cost: $X.XXXX` summary
- `inspect <trace_id>` — open the browser viewer for a trace; shows spans always, Flow tabs if results are available (prompts to compute if not)
- `supplement [SESSION_ID]` — enrich Claude Code OTLP spans with unredacted assistant text, thinking blocks, and full tool outputs by uploading the local `~/.claude/projects/<slug>/<session>.jsonl` file. `--latest` picks the most-recently-modified session JSONL; `--all <dir>` walks a whole project directory; `--session-file PATH` overrides the auto-lookup; `--with-subagents` synthesises child spans under parent Task tool_invocations (stretch); `--dry-run` reports without writing; `--force` re-supplements already-supplemented spans. The command gzip-compresses the JSONL body and POSTs it to `/api/v1/supplement/claude_code` so WSL2 volume-mount friction doesn't bite.

## Conventions

- Never add external dependencies — keep the install footprint at zero
- The CLI is a thin HTTP client; business logic lives in the backend
- Flow columns in `trace_metrics` are NULL until `gigaflow compute` is run for a trace
