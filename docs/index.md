# GigaFlow CLI

Command-line client for **GigaFlow** — connect your LLM/agent traces to a GigaFlow
backend and run **Flow analysis** on them: atomize each step, attribute information
flow between atoms, score groundedness / relevance / fulfilment, and diagnose
failures.

The CLI is a thin, **zero-dependency** client (Python standard library only). Your
traces live in an observability platform (Arize Phoenix, Logfire, Braintrust,
MLflow, W&B Weave) or are sent via OTLP; the backend does the compute; this CLI
drives **ingest → compute → inspection**.

## Install

```bash
pip install gigaflow
```

## Configure

```bash
export GIGAFLOW_API_KEY=<your GigaFlow API key>
```

`gigaflow login` (browser sign-in) or `gigaflow setup` persist these to
`~/.gigaflow/config.json`, so the exports are optional on later runs.

## End-to-end in five commands

```bash
gigaflow setup                                   # pick your tracing tool, connect it, sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>                      # open the browser Flow viewer
gigaflow query "SELECT trace_id, groundedness, total_cost_usd FROM trace_metrics ORDER BY total_cost_usd DESC LIMIT 20"
```

## Where to next

- **[Connect a trace source](sources/README.md)** — Arize Phoenix, Logfire,
  Braintrust, MLflow, W&B Weave, or direct OTLP.
- **[Querying](querying.md)** — explore the `trace_metrics` view with SQL.
- **[Transform configs](transforms.md)** — map raw vendor spans to GigaFlow
  primitives.
- **[Changelog](changelog.md)** — release history.

The full command reference lives in the project
[README](https://github.com/GigaFlow-AI-Incorporated/gigaflow-sdk#readme).
