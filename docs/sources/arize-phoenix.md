# Arize Phoenix

The built-in, wizard-driven source. GigaFlow reads Phoenix's `spans` table over a
direct Postgres connection.

## Prerequisites
- A Phoenix Postgres instance reachable from the backend, and its connection
  string: `postgresql://user:pass@host:5432/dbname`.
- The table name (default `spans`).

## Connect (wizard)
```bash
export GIGAFLOW_BACKEND_URL=https://api.gigaflow.io/api/v1
export GIGAFLOW_API_KEY=<your key>
gigaflow setup
```
The wizard: creates a project → uploads the bundled `arize_phoenix.yml` transform
→ registers the datasource (`source_type=arize_phoenix`, `source_table=spans`) →
runs the first sync.

## Connect (API, if you prefer)
```bash
PID=$(curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"my-phoenix-project"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')

curl -X PUT "$GIGAFLOW_BACKEND_URL/projects/$PID/transform" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: text/plain' --data-binary @gigaflow/transforms/arize_phoenix.yml

curl -X POST "$GIGAFLOW_BACKEND_URL/datasources/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d "{
    \"project_id\": \"$PID\",
    \"name\": \"my-phoenix\",
    \"source_type\": \"arize_phoenix\",
    \"connection_url\": \"postgresql://user:pass@host:5432/phoenix\",
    \"source_table\": \"spans\"
  }"
```

## Transform
Bundled: `gigaflow/transforms/arize_phoenix.yml` (maps OpenInference `span_kind` +
`attributes.*`). If your Phoenix uses non-standard attribute paths, copy it, edit,
and pass the path during `setup` (or `PUT .../transform`).

## Run
```bash
gigaflow sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
