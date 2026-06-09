# Connecting a trace source

GigaFlow ingests traces from an observability platform (or directly via OTLP),
maps each span to a GigaFlow **primitive** with a transform config, then runs Flow
analysis. This directory has one guide per source.

For the five platforms below, the whole connection is driven by **`gigaflow setup`**:
it signs you in with your waitlist email (same as `gigaflow login`), asks which
platform you use, collects the connection details, then creates a project, applies
a transform, registers the datasource, and runs the first sync. You never set a
GigaFlow API key or backend URL by hand.

| Source | What you provide | Source identifier | Bundled transform |
|---|---|---|---|
| [Arize Phoenix](arize-phoenix.md) | Postgres connection | table name (`spans`) | ✅ works out of the box |
| [Logfire](logfire.md) | read token | project base URL | ✅ works out of the box |
| [Braintrust](braintrust.md) | API key | project **name** | ✅ bundled (may need tailoring) |
| [MLflow](mlflow.md) | token (or none) | server URL | ✅ bundled (may need tailoring) |
| [W&B Weave](wb-weave.md) | `WANDB_API_KEY` | `entity/project` | ⚠️ template — tailor to your ops |

When the wizard asks for a transform, leave it blank to use the bundled one, or
point it at your own `transform.yml`. Sync is **append-only**: re-running never
deletes traces; already-imported ones are skipped.

## Direct OTLP

[Direct OTLP](otlp.md) is the exception — the no-platform path where you point your
app's OpenTelemetry exporter straight at GigaFlow. It isn't part of the `gigaflow
setup` wizard and is a more advanced, API-driven setup; see its guide.
