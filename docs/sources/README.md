# Connecting a trace source

GigaFlow ingests traces from an observability platform (or directly via OTLP),
maps each span to a GigaFlow **primitive** with a transform config, then runs
Flow analysis. This directory has one guide per source.

| Source | Auth | Source identifier | Bundled transform |
|---|---|---|---|
| [Arize Phoenix](arize-phoenix.md) | Postgres connection string | table name (`spans`) | ✅ `arize_phoenix.yml` |
| [Logfire](logfire.md) | read token (Bearer) | project base URL | ✅ `logfire.yml` |
| [Braintrust](braintrust.md) | API key (Bearer) | project **name** | ⚠️ custom |
| [MLflow](mlflow.md) | token (Bearer) or none | experiment(s) on the server | ⚠️ custom |
| [W&B Weave](wb-weave.md) | `WANDB_API_KEY` (Basic) | `entity/project` | ⚠️ custom |
| [Direct OTLP](otlp.md) | per-project OTLP token | — | per-project transform |

All datasource fields map to one model (`POST /api/v1/datasources/`):

| Field | Meaning |
|---|---|
| `project_id` | the GigaFlow project (create with `POST /api/v1/projects/`) |
| `name` | a label for this datasource |
| `source_type` | one of `arize_phoenix` · `logfire` · `mlflow` · `braintrust` · `wb_weave` |
| `connection_url` | DB connection string (Phoenix) or API base URL (everyone else) |
| `source_table` | table name (Phoenix) **or** project identifier (Braintrust name, Weave `entity/project`) |
| `api_key` | Bearer token for HTTP sources; omit for Phoenix |
| `ui_base_url` | optional; auto-discovered for Logfire/MLflow/Braintrust — powers source-link buttons in the viewer |

Sync is **append-only**: re-running never deletes traces; already-imported ones
(matched by `(project_id, source_trace_id)`) are skipped.
