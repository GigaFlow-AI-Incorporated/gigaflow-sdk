# Logfire (Pydantic)

GigaFlow queries Logfire's FusionFire Query API. **Bundled transform** —
`gigaflow/transforms/logfire.yml` handles pydantic-ai/Logfire spans.

## Prerequisites
- A Logfire **read token** (Logfire → project → Settings → Read tokens).
- Your project's API base, e.g. `https://logfire-us.pydantic.dev/<org>/<project>`
  (the org segment is your Logfire org/username slug).

## Connect (API)
```bash
PID=$(curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"my-logfire-project"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')

curl -X PUT "$GIGAFLOW_BACKEND_URL/projects/$PID/transform" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: text/plain' --data-binary @gigaflow/transforms/logfire.yml

curl -X POST "$GIGAFLOW_BACKEND_URL/datasources/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d "{
    \"project_id\": \"$PID\",
    \"name\": \"my-logfire\",
    \"source_type\": \"logfire\",
    \"connection_url\": \"https://logfire-us.pydantic.dev/<org>/<project>\",
    \"api_key\": \"<logfire read token>\"
  }"
```
Optional: set `service_name_filter` on the datasource to restrict sync to one
service (Logfire is the only source that honours it).

## Run
```bash
gigaflow sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
