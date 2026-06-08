# gigaflow CLI

Command-line client for **GigaFlow** — connect your LLM/agent traces to a GigaFlow
backend and run **Flow analysis** on them (atomize each step, attribute information
flow between atoms, score groundedness/relevance/fulfilment, diagnose failures).

The CLI is a thin client: your traces live in an observability platform (Arize
Phoenix, Logfire, Braintrust, MLflow, W&B Weave) or are sent via OTLP; the backend
does the compute; this CLI drives ingest → compute → inspection.

📖 **Documentation:** <https://docs.gigaflow.io/>

---

## Install

```bash
# From source (current):
git clone https://github.com/GigaFlow-AI-Incorporated/gigaflow-sdk
cd gigaflow-sdk && pip install -e .

# From PyPI (once published):
pip install gigaflow
```

The CLI is standard-library only — nothing else to pull in.

## Configure the backend + key

Two independent credentials:

| Credential | Env var | Where it goes | Purpose |
|---|---|---|---|
| **GigaFlow API key** | `GIGAFLOW_API_KEY` | `Authorization: Bearer` header | Authenticates you to the GigaFlow backend. Required on any hosted backend. |
| **OpenAI API key** | `OPENAI_API_KEY` | `compute` request body | Required by the CLI's `compute` command. *On the hosted service, Flow LLM calls currently run on GigaFlow's platform key; per-customer key billing is on the roadmap.* |

```bash
export GIGAFLOW_BACKEND_URL=https://api.gigaflow.io/api/v1
export GIGAFLOW_API_KEY=<your GigaFlow API key>
export OPENAI_API_KEY=sk-...
```

**Resolution order** (first set wins):
- Backend URL: `--backend <url>` > `$GIGAFLOW_BACKEND_URL` > saved config > `http://localhost:8000/api/v1`
- API key: `--api-key <key>` > `$GIGAFLOW_API_KEY` > saved config > none

`gigaflow setup` also prompts for these and persists them to `~/.gigaflow/config.json`,
so the exports are optional on later runs.

---

## The end-to-end flow

```bash
# 1. Connect a trace source (creates a project + registers a datasource).
#    Arize Phoenix is wizard-driven; other vendors are a one-time API call.
#    → see docs/sources/<vendor>.md
gigaflow setup                  # Arize Phoenix wizard
# (or register another source via the API — see the per-vendor docs)

# 2. Pull traces into GigaFlow.
gigaflow sync

# 3. Compute Flow for every trace that doesn't have results yet.
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"

# 4. Open a trace in the browser viewer (Trace / Orchestration / Atomic / Metrics).
gigaflow inspect <trace_id>

# 5. Query results as data.
gigaflow query "SELECT trace_id, groundedness, total_cost_usd FROM trace_metrics ORDER BY total_cost_usd DESC LIMIT 20"
```

## Connect your trace source

Pick your platform — each guide covers the exact datasource config + whether a
custom transform is needed:

| Source | Setup | Bundled transform? | Guide |
|---|---|---|---|
| **Arize Phoenix** | `gigaflow setup` wizard | ✅ yes | [docs/sources/arize-phoenix.md](docs/sources/arize-phoenix.md) |
| **Logfire** | API datasource | ✅ yes | [docs/sources/logfire.md](docs/sources/logfire.md) |
| **Braintrust** | API datasource | ⚠️ custom transform | [docs/sources/braintrust.md](docs/sources/braintrust.md) |
| **MLflow** | API datasource | ⚠️ custom transform | [docs/sources/mlflow.md](docs/sources/mlflow.md) |
| **W&B Weave** | API datasource | ⚠️ custom transform | [docs/sources/wb-weave.md](docs/sources/wb-weave.md) |
| **Direct OTLP** | project token + exporter | n/a (per-project transform) | [docs/sources/otlp.md](docs/sources/otlp.md) |

> Only Arize Phoenix has a wizard today; the others register a datasource with a
> single `POST /api/v1/datasources/` call (shown in each guide), then `gigaflow sync`.

## Commands

| Command | What it does |
|---|---|
| `gigaflow setup` | First-run wizard (Arize Phoenix): backend, project, transform, datasource, sync |
| `gigaflow sync` | Pull traces from the configured datasource (append-only) |
| `gigaflow traces` | List traces (auto-syncs first) |
| `gigaflow spans <trace_id>` | List spans for a trace |
| `gigaflow compute "<SQL>"` | Batch-compute Flow for matching traces |
| `gigaflow inspect <trace_id>` | Open the browser viewer |
| `gigaflow query "<SQL>"` | Run SQL against the `trace_metrics` view (read-only) — see [QUERYING.md](QUERYING.md) |
| `gigaflow config show` / `clear` | Show / reset saved config |

## Transform configs

A **transform config** (YAML) maps a source's raw spans to GigaFlow primitives
(`llm_call`, `tool_invocation`, `user_input`, `transform`) via `filter` (classify)
and `mapping` (extract fields). Bundled configs ship for Arize Phoenix and Logfire
(`gigaflow/transforms/`); other sources need a custom one (each vendor guide explains
the shape). Re-upload to an existing project without re-running setup:

```bash
curl -X PUT "$GIGAFLOW_BACKEND_URL/projects/<project_id>/transform" \
  -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H "Content-Type: text/plain" --data-binary @my_transform.yml
```

Re-`sync` after changing a transform to reclassify spans.

Full grammar + the per-project upload flow: [docs/transforms.md](docs/transforms.md).

## Publish to PyPI

See the release steps in [docs/publishing.md](docs/publishing.md) (token reserved
in the company vault; CI publish is wired in the infra repo).
