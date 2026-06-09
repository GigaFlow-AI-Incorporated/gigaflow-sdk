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
pip install gigaflow
```

The CLI is standard-library only — nothing else to pull in.

## Sign in

Run `gigaflow login` — it signs you in with your waitlist email and stores your
credentials in `~/.gigaflow/config.json`, so you only do it once:

```bash
gigaflow login
```

`gigaflow setup` also signs you in automatically, so a fresh user can go straight
to setup — no API key or backend URL needed; the hosted service
(`https://api.gigaflow.io/api/v1`) is the default.

Flow compute additionally needs an **OpenAI key** (sent only by the `compute`
command):

```bash
export OPENAI_API_KEY=sk-...
```

*On the hosted service, Flow LLM calls currently run on GigaFlow's platform key;
per-customer key billing is on the roadmap.*

For repeatable or CI setups, see the [gigaflow.env reference](https://docs.gigaflow.io/gigaflow-env/).

**Developer / self-hosted overrides** (hosted users don't need these):

| Env var | Purpose |
|---|---|
| `GIGAFLOW_BACKEND_URL` | Point the CLI at a non-default backend. Same as `--backend`. |
| `GIGAFLOW_API_KEY` | Static bearer key, bypassing interactive login. Same as `--api-key`. |

**Resolution order** (first set wins):
- Backend URL: `--backend <url>` > `$GIGAFLOW_BACKEND_URL` > saved config > the hosted service (`https://api.gigaflow.io/api/v1`)
- API key: `--api-key <key>` > `$GIGAFLOW_API_KEY` > saved config > none

---

## The end-to-end flow

```bash
# 1. Connect a trace source (creates a project + registers a datasource).
#    All five vendors are wizard-driven; → see docs/sources/<vendor>.md
gigaflow setup                  # interactive vendor wizard

# 2. Pull traces into GigaFlow.
gigaflow sync

# 3. Compute Flow for every trace that doesn't have results yet.
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"

# 4. Open a trace in the browser viewer (Trace / Orchestration / Atomic / Metrics).
gigaflow inspect <trace_id>
```

## Supported tracing backends

`gigaflow setup` walks you through connecting one of:

- **Arize Phoenix** — PostgreSQL connection to the Phoenix spans DB
- **Braintrust** — API base URL + project name + API key
- **Logfire** — API base URL + read token
- **MLflow** — tracking server URL (+ optional token)
- **W&B Weave** — trace server URL + `<entity>/<project>` + W&B API key

Each gets a built-in transform; Braintrust/MLflow/Arize work out of the box; Logfire works out of the box for pydantic-ai projects; W&B Weave ships a template you tailor to your op names. The wizard previews how your spans classified so you can spot a mismatch immediately.

## Connect your trace source

Pick your platform — each guide covers the exact datasource config + whether a
custom transform is needed:

| Source | Setup | Bundled transform? | Guide |
|---|---|---|---|
| **Arize Phoenix** | `gigaflow setup` wizard | ✅ yes | [docs/sources/arize-phoenix.md](docs/sources/arize-phoenix.md) |
| **Logfire** | `gigaflow setup` wizard | ✅ yes | [docs/sources/logfire.md](docs/sources/logfire.md) |
| **Braintrust** | `gigaflow setup` wizard | ✅ yes | [docs/sources/braintrust.md](docs/sources/braintrust.md) |
| **MLflow** | `gigaflow setup` wizard | ✅ yes | [docs/sources/mlflow.md](docs/sources/mlflow.md) |
| **W&B Weave** | `gigaflow setup` wizard | ⚠️ template (see note) | [docs/sources/wb-weave.md](docs/sources/wb-weave.md) |
| **Direct OTLP** | project token + exporter | n/a (per-project transform) | [docs/sources/otlp.md](docs/sources/otlp.md) |

> `gigaflow setup` supports all five vendors. W&B Weave ships a template transform
> (`wb_weave.yml`) rather than a fully generic one — Weave has no structural span-type
> field, so you may need to tailor filter rules to your op names. The setup wizard
> previews classification so you can spot a mismatch immediately.

## Commands

| Command | What it does |
|---|---|
| `gigaflow setup` | First-run wizard (all five vendors): pick vendor, enter connection, name project, upload transform, sync, preview |
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
and `mapping` (extract fields). Bundled configs ship for all five vendors
(`gigaflow/transforms/`); W&B Weave's is a template you may need to tailor to your
op names. Leave the transform prompt blank in `gigaflow setup` to use the bundled
one. Re-upload to an existing project without re-running setup:

```bash
curl -X PUT "$GIGAFLOW_BACKEND_URL/projects/<project_id>/transform" \
  -H "Authorization: Bearer $GIGAFLOW_API_KEY" \
  -H "Content-Type: text/plain" --data-binary @my_transform.yml
```

Re-`sync` after changing a transform to reclassify spans.

Full grammar + the per-project upload flow: [docs/transforms.md](docs/transforms.md).
