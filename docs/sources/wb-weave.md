# Weights & Biases — Weave

GigaFlow reads Weave calls via the W&B trace-server API. **No bundled transform** —
supply a custom one.

## Prerequisites
- `WANDB_API_KEY` (wandb.ai → Settings → API keys) — sent as HTTP Basic `api:<key>`.
- Your Weave project id as **`entity/project`** (e.g. `my-team/my-agent`).
- Base URL `https://trace.wandb.ai` (default; override for self-hosted).

## Connect (API)
```bash
PID=$(curl -s -X POST "$GIGAFLOW_BACKEND_URL/projects/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"my-weave-project"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')

# upload your custom transform first, then:
curl -X POST "$GIGAFLOW_BACKEND_URL/datasources/" -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H 'Content-Type: application/json' -d "{
    \"project_id\": \"$PID\",
    \"name\": \"my-weave\",
    \"source_type\": \"wb_weave\",
    \"connection_url\": \"https://trace.wandb.ai\",
    \"source_table\": \"<entity>/<project>\",
    \"api_key\": \"<WANDB_API_KEY>\"
  }"
```

## Transform
Weave calls normalize to nested dicts with `attributes.*`, `inputs`, `output`,
`op_name`, `display_name`. Author a transform mapping these to primitives (template:
`gigaflow/transforms/arize_phoenix.yml`). Upload via `PUT /projects/$PID/transform`.

## Run
```bash
gigaflow sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
