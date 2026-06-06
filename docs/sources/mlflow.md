# MLflow

GigaFlow reads MLflow traces over the MLflow REST API (OSS or Databricks).
**No bundled transform** — supply a custom one (see Transform below).

## Prerequisites
- MLflow server base URL: `http://host:5000` (OSS) or your Databricks workspace URL.
- Auth: a Databricks PAT (`api_key`) for Databricks; omit `api_key` for anonymous OSS.

## Connect (API)
```bash
PID=$(curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"my-mlflow-project"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')

# upload your custom transform (see below), then:
curl -X POST "$GIGAFLOW_BACKEND_URL/datasources/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d "{
    \"project_id\": \"$PID\",
    \"name\": \"my-mlflow\",
    \"source_type\": \"mlflow\",
    \"connection_url\": \"http://your-mlflow:5000\",
    \"api_key\": \"<Databricks PAT, or omit for OSS>\"
  }"
```

## Transform
MLflow spans arrive as OTLP proto-JSON, normalized to nested dicts (ns→ms, base64
ids decoded, `mlflow.experiment_id` injected). Author a transform mapping
`attributes.*` / `name` to primitives — use `gigaflow/transforms/arize_phoenix.yml`
as a grammar template. Upload via `PUT /projects/$PID/transform`.

## Run
```bash
gigaflow sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
