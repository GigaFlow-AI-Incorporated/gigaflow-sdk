# Braintrust

GigaFlow pulls Braintrust **project logs** via the Braintrust REST API. `gigaflow setup` now walks you through Braintrust interactively (recommended). The manual API-call flow below remains available for scripting.

## Prerequisites
- A **Braintrust API key** (Settings → API keys).
- Your **Braintrust project name** (exactly as it appears in Braintrust). The
  reader resolves it to the project UUID, then pages `POST /v1/project_logs/{id}/fetch`.
- API base URL: `https://api.braintrust.dev` (default; override for EU/self-hosted).

## 1. Create a project
```bash
export GIGAFLOW_BACKEND_URL=https://api.gigaflow.io/api/v1
export GIGAFLOW_API_KEY=<your GigaFlow key>

PID=$(curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/" \
  -H "Authorization: Bearer $GIGAFLOW_API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"my-braintrust-project"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')
echo "project_id=$PID"
```

## 2. Provide a transform config
> **Tip:** leave the transform blank in `gigaflow setup` to use the bundled `braintrust.yml`.

If you need to customise, author a transform that maps
Braintrust's normalized fields to GigaFlow primitives. After the reader normalizes a
Braintrust event, these dotted keys are available to `mapping`:
`input`, `output`, `metadata.*`, `metrics.*`, `span_attributes.*`, `name`.

Start from the bundled `gigaflow/transforms/arize_phoenix.yml` as a structural
template (same `filter` + `mapping` grammar) and retarget the paths. Minimal sketch:
```yaml
# braintrust.yml (illustrative — adjust to your span shape)
primitives:
  - type: llm_call
    filter: { field: span_attributes.type, equals: llm }
    mapping:
      prompt: input
      completion: output
      model: metadata.model
  - type: tool_invocation
    filter: { field: span_attributes.type, equals: tool }
    mapping:
      tool_name: name
      tool_input: input
      tool_output: output
  - type: user_input
    filter: { field: span_attributes.type, equals: function }   # adjust
    mapping:
      content: input
```
Then upload it:
```bash
curl -X PUT "$GIGAFLOW_BACKEND_URL/projects/$PID/transform" \
  -H "Authorization: Bearer $GIGAFLOW_API_KEY" -H 'Content-Type: text/plain' \
  --data-binary @braintrust.yml
```
> Tip: run `gigaflow sync` then `gigaflow spans <trace_id>` to see the raw fields,
> iterate on the transform, and re-sync (sync is append-only + reclassifies).

## 3. Register the Braintrust datasource
`source_table` carries the **project name**; `api_key` is your Braintrust key.
```bash
curl -X POST "$GIGAFLOW_BACKEND_URL/datasources/" \
  -H "Authorization: Bearer $GIGAFLOW_API_KEY" -H 'Content-Type: application/json' \
  -d "{
    \"project_id\": \"$PID\",
    \"name\": \"my-braintrust\",
    \"source_type\": \"braintrust\",
    \"connection_url\": \"https://api.braintrust.dev\",
    \"source_table\": \"<your Braintrust project name>\",
    \"api_key\": \"<your Braintrust API key>\"
  }"
```
(`ui_base_url` is auto-discovered so the viewer's source-link buttons deep-link
back to Braintrust.)

## 4. Sync, compute, inspect
```bash
gigaflow sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```

## Notes
- The reader pages 1000 events/request (max 200 pages) and dedupes by event id.
- Braintrust timestamps are float seconds — handled by the reader.
- If `sync` returns `inserted: 0`, check the project name (must match exactly) and
  that the API key can read that project.
