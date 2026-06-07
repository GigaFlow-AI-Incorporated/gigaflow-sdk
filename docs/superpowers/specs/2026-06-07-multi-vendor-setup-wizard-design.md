# Multi-vendor setup wizard — design

**Date:** 2026-06-07
**Status:** Draft (awaiting review)
**Repo:** `gigaflow-sdk` (CLI), with a small dependency on `gigaflow` backend

## Problem

`gigaflow setup` is hard-coded to the **Arize Phoenix** shape end to end, even
though the backend already ingests five source types (`arize_phoenix`,
`braintrust`, `logfire`, `mlflow`, `wb_weave`). Concretely, `run_wizard()` in
`gigaflow/_setup.py`:

- Step 2 defaults the project name to `arize-phoenix-project` and uploads the
  built-in **Arize** `transform.yml`.
- Step 3 demands a PostgreSQL `host / port / user / password / db / table` — the
  Arize Phoenix connection shape. None of this applies to the HTTP-API vendors.
- Step 4 registers the datasource **without** sending `source_type` or `api_key`,
  so every datasource is silently created as `arize_phoenix`.

A Braintrust user therefore has no supported path through the CLI — they must
hand-roll `curl` calls (see `examples/braintrust/fabricated_quote_demo/e2e.sh`).
The subcommand help still reads "Configure GigaFlow with an Arize Phoenix
datasource."

A second, subtler friction: there are **two different "projects"** in the flow
and the wizard conflates them — the **GigaFlow project** (a container created via
`POST /projects/`) and the **vendor project** (e.g. the Braintrust project name,
stored in the datasource's `source_table` column).

## Goals

1. The wizard asks **which tracing tool** the user has and branches accordingly —
   no assumption of Arize.
2. All five backend-supported vendors are selectable.
3. Each vendor collects only the fields it actually needs, with sensible defaults.
4. The GigaFlow-project concept is explained, and its name is auto-suggested from
   the vendor project name where one exists.
5. Best-effort **generic transforms** ship for as many vendors as is honestly
   possible, so most users never write a `transform.yml`.
6. An **interactive preview/confirm loop** shows how the user's real spans got
   classified before committing, eliminating the "synced zero useful spans"
   failure mode.

## Non-goals

- A first-party tracing SDK (separate idea — see `gigaideas`).
- Re-transforming already-imported traces (sync is append-only; out of scope).
- Editing an existing datasource's vendor/connection (already out of scope in the
  datasources API v1).

## Key findings (grounding)

### Backend datasource contract

`POST /api/v1/datasources/` (`DataSourceCreate`) accepts and persists:
`project_id`, `name`, `connection_url`, `source_table` (default `"spans"`),
`source_type` (default `"arize_phoenix"`), `api_key`, `ui_base_url`. The handler
auto-discovers `ui_base_url` for logfire/mlflow/braintrust/wb_weave when omitted.

`POST /api/v1/datasources/{id}/sync` **requires** `project.transform_config`
(returns 422 otherwise) for **every** source type — the HTTP readers normalize
the raw vendor payload into the flat span shape, but the transform still runs on
top to classify spans into primitives.

### Per-vendor connection shape

| Vendor | `connection_url` (default) | `source_table` | `api_key` |
|---|---|---|---|
| arize_phoenix | `postgresql://user:pass@host:port/db` (built from prompts) | table name (`spans`) | unused |
| braintrust | `https://api.braintrust.dev` | project **name** | required |
| logfire | `https://logfire-us.pydantic.dev` | ignored | required (read token) |
| mlflow | tracking server URL (no default) | ignored | optional (Databricks PAT) |
| wb_weave | `https://trace.wandb.ai` | `<entity>/<project>` | required (W&B key) |

### Transform feasibility — the decisive finding

A transform classifies each span via a `filter` (`field` + `value` + `mode`) then
maps fields by dot-path. A **generic** transform is only possible when the vendor
emits a **structural span-type field** (independent of how the user named their
spans). Findings:

| Vendor | Structural classifier | Generic transform |
|---|---|---|
| arize_phoenix | `span_kind` column (`LLM`/`TOOL`/`AGENT`/`RETRIEVER`) | **ships today** (`arize_phoenix.yml`) |
| logfire | pydantic-ai span-name conventions (`chat …`, `running tool …`, `agent run`) | **ships today** (`logfire.yml`) |
| braintrust | `span_attributes.type` (`llm`/`tool`/`function`) — set by the Braintrust SDK `start_span(type=…)`; preserved by `braintrust_reader.py` | **new — achievable** |
| mlflow | `attributes.mlflow.spanType` (`LLM`/`TOOL`/`AGENT`…) — MLflow `SpanType` exported as an attribute; reader expands all attributes | **new — achievable, pending fixture verification** |
| wb_weave | none — Weave only has the op/function name; attribute schema is user-defined | **template only** (convention-based) |

So four of five vendors can get a true generic transform classifying on a
structural field. Only W&B Weave is fundamentally convention-dependent and relies
on the preview loop + a documented starter template.

Field locations for the new generic transforms (after each reader normalizes):

- **braintrust** — classify on `span_attributes.type`. llm: `input` → input,
  `output` → completion, `metadata.gen_ai.request.model` → model (fallback
  `metadata.model`), `metrics.prompt_tokens`/`metrics.completion_tokens` →
  tokens. tool: `input` → tool_input, `output` → tool_output. user/root
  (`type == "function"` root, or first span): `input` → content.
- **mlflow** — classify on `attributes.mlflow.spanType`. llm:
  `attributes.mlflow.spanInputs` → input, `attributes.mlflow.spanOutputs` →
  completion, `attributes.gen_ai.request.model` → model. tool: spanInputs →
  tool_input, spanOutputs → tool_output. agent: spanInputs → content.
- **wb_weave** — template classifying on `op_name`/`span_name` convention with
  attribute-probe fallback (`attributes.gen_ai.system` for llm,
  `attributes.gen_ai.tool.name` for tool). llm: `inputs` → input, `output` →
  completion, `summary.usage.prompt_tokens`/`completion_tokens` → tokens. tool:
  `inputs` → tool_input, `output` → tool_output.

> The exact dot-paths above are derived from the readers and the per-vendor
> example `transform.yml` files. The implementation plan will validate each new
> transform against the corresponding example fixture before shipping.

## Approach

**Vendor-strategy registry** (chosen over inline `if/elif` and over per-vendor
subcommands). Each vendor is a small self-contained descriptor:

```
VendorSpec:
  key            # source_type, e.g. "braintrust"
  label          # "Braintrust (REST API)"
  collect(env)   # prompts for connection details → returns
                 #   {connection_url, source_table, api_key, vendor_project_name?}
  default_transform   # built-in YAML name, or None for "must supply / template"
  transform_quality   # "generic" | "template"
```

`run_wizard()` becomes: backend → **pick vendor** → run that vendor's
`collect()` → project → transform → register+preview+sync. Adding a sixth vendor
is one descriptor + one transform file.

## Wizard flow

```
GigaFlow Setup Wizard

Step 1  Backend            backend URL + GigaFlow API key            (unchanged)
Step 2  Tracing tool       pick 1–5  → source_type                   (NEW)
Step 3  Connection         vendor-specific prompts via collect()     (BRANCH)
Step 4  Project            explain GigaFlow project; name defaults
                           to the vendor project name where present  (NEW copy)
Step 5  Transform          generic built-in (Arize/Logfire/
                           Braintrust/MLflow) OR template+guidance
                           (Weave); always allow override            (BRANCH)
Step 6  Register + preview register datasource (now sends source_type
                           + api_key) → preview classification →
                           confirm or fix → sync                     (NEW loop)
```

### Step 2 — vendor picker

```
Which tracing tool are you using?
  1) Arize Phoenix   (Postgres)
  2) Braintrust      (REST API)
  3) Logfire         (REST API)
  4) MLflow          (REST API)
  5) W&B Weave       (REST API)
>
```

### Step 3 — connection (per vendor)

- **Arize Phoenix** — the existing Postgres block (host/port/user/password/db/
  table), builds `postgresql://…`. No `api_key`.
- **Braintrust** — API base `[https://api.braintrust.dev]`, project **name**, API
  key. `source_table = project name`.
- **Logfire** — API base `[https://logfire-us.pydantic.dev]`, read token.
  `source_table` left default.
- **MLflow** — tracking server URL, optional token.
- **W&B Weave** — trace server `[https://trace.wandb.ai]`, `<entity>/<project>`,
  W&B key. `source_table = <entity>/<project>`.

Each prefers values from a supplied `gigaflow.env` (keeping the existing env-file
behavior), then falls back to the default / a prompt.

### Step 4 — project

Short explanation: "GigaFlow groups your traces under a *project*." Where the
vendor has a real project identifier (Braintrust name, Weave `<entity>/<project>`)
the GigaFlow project name **defaults to it**. For Arize/Logfire/MLflow (no such
identifier) it falls back to a sensible default with the one-line explanation.

### Step 5 — transform

- Arize / Logfire / Braintrust / MLflow → use the built-in generic transform by
  default; user may override with a path.
- W&B Weave → ships a documented starter template; the wizard explains it is
  convention-dependent and points at `examples/wb_weave/.../transform.yml` (or
  the bundled template) as the starting point.
- In all cases the existing "supply your own `transform.yml` path" escape hatch
  remains.

### Step 6 — register, preview, confirm, sync (the friction-killer)

After the transform is chosen, **preview classification on the user's real
spans** before committing:

```
Previewing how your spans classify…
  12 spans sampled → 3 llm_call · 4 tool_invocation · 1 user_input · 4 unmatched
  Looks good? [Y/n]
```

- **Good** → proceed to the real sync, show the span preview, save config.
- **Poor** (e.g. everything unmatched) → show the actual span types/names seen,
  explain the transform didn't match, and offer: try a different built-in /
  supply your own `transform.yml` / open docs — then re-preview.

**Preview mechanism (open implementation question).** Sync is append-only and
requires the transform *before* syncing, so the preview should ideally be a
**dry-run**: fetch a small sample via the reader and apply the transform
**without persisting**. Whether a dry-run endpoint exists or needs a small
backend addition (`gigaflow` repo) is to be resolved in the implementation-plan
phase. Two viable shapes:

1. **Backend dry-run endpoint** (preferred) — e.g. `POST /datasources/preview`
   that fetches N raw spans via the reader, applies a posted transform, and
   returns per-primitive counts + sample classifications. Clean; no writes.
2. **Sync-then-inspect fallback** — register + sync, run the existing
   `_show_span_preview`, and if classification is poor guide the user to
   `gigaflow config clear` + re-run with a different transform. Works with zero
   backend change but is heavier on a miss.

The wizard UX is identical either way; only the plumbing differs.

### Also fixed

- `commands/setup.py` subcommand help → vendor-neutral ("Configure GigaFlow with
  a tracing datasource").

## Files touched (anticipated)

`gigaflow-sdk`:
- `gigaflow/_setup.py` — vendor registry, branched wizard, register call now
  sends `source_type` + `api_key`, preview/confirm loop.
- `gigaflow/commands/setup.py` — help text.
- `gigaflow/transforms/braintrust.yml`, `mlflow.yml`, `wb_weave.yml` — new
  best-effort transforms (Weave = template).
- Tests for the registry, each vendor branch, and the preview loop.

`gigaflow` (only if dry-run preview is chosen):
- A small `datasources` preview endpoint + its bundled-transform copies under
  `app/ingest/transforms/` (keep in sync with the CLI, per the in-file header).

## Testing

- Unit-test each `VendorSpec.collect()` for field/default/env-precedence behavior.
- Validate each new transform parses (`TransformConfig`) and classifies its
  vendor's example fixture into the expected primitive counts.
- Test the preview/confirm loop: good path proceeds; poor path re-prompts and
  accepts an override.
- Keep the existing Arize end-to-end path green (regression).

## Open questions

1. Preview mechanism — dry-run endpoint vs sync-then-inspect (above).
2. MLflow `attributes.mlflow.spanType` export path — confirm against a real
   MLflow OTLP fixture during implementation.
3. W&B Weave template — ship as a bundled `transforms/wb_weave.yml` (selectable)
   or only as an `examples/` reference the wizard points to?
```
