# Direct OTLP ingest

Skip the third-party platform entirely: point your app's OpenTelemetry exporter at
GigaFlow's OTLP receiver. No datasource/`sync` — spans arrive in real time.

## Endpoint
- **HTTP:** `POST https://api.gigaflow.io/v1/traces` (accepts `application/json`
  and `application/x-protobuf`). Logs: `POST .../v1/logs`.
- gRPC (`:4317`) runs locally / under docker-compose but is **not exposed on the
  hosted endpoint** yet — use HTTP in production.

## 1. Create a project + mint an OTLP token
```bash
PID=$(curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"my-otlp-project"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')

# Mint a per-project OTLP token (returned ONCE, prefixed gflw_otlp_):
curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/$PID/otlp_tokens" \
  -H "Authorization: Bearer $GIGAFLOW_API_KEY"
```
The token scopes ingest to this project (clients can't smuggle traces across
projects). Manage with `GET`/`DELETE .../projects/$PID/otlp_tokens`.

## 2. Point your exporter at GigaFlow
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.gigaflow.io
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer gflw_otlp_..."
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```
(Use the OpenInference / OpenLLMetry / pydantic-ai instrumentation for your stack.)

## 3. Transform + compute
Set the project's transform to match your exporter's span shape (`PUT
/projects/$PID/transform`). Then traces appear without `sync`:
```bash
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```

See the backend's `docs/otlp-quickstart.md` for exporter snippets per framework.
