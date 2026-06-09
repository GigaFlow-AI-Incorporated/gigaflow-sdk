# MLflow

GigaFlow reads MLflow traces over the MLflow REST API (OSS or Databricks). A
bundled transform (`mlflow.yml`) ships as a starting point.

## What you'll need
- MLflow server base URL: `http://host:5000` (OSS) or your Databricks workspace URL.
- Auth: a Databricks PAT for Databricks; nothing for anonymous OSS.

## Connect

Run the setup wizard. The first time, it signs you in with your waitlist email
(same as `gigaflow login`), then walks you through the connection above:

```bash
gigaflow setup
```

Pick **MLflow** when prompted and enter your server URL (and a Databricks PAT if
needed). The wizard creates a GigaFlow project, applies a transform, registers the
datasource, and runs the first sync — you never set an API key or backend URL by
hand.

## Transform

MLflow spans arrive as OTLP proto-JSON, normalized to nested dicts (ns→ms, base64
ids decoded, `mlflow.experiment_id` injected). The bundled `mlflow.yml` is a
starting point; if your spans use non-standard `attributes.*` / `name` paths, copy
it, edit, and give the wizard the path to your edited file when it asks for a
transform.

## After the first sync

```bash
gigaflow sync                                    # re-pull new traces anytime
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
