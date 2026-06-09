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

## Sign in

```bash
gigaflow login
```

`gigaflow login` opens your browser to sign in and stores your credentials in
`~/.gigaflow/config.json`, so you only do it once.

## End-to-end in three commands

```bash
gigaflow setup                                   # pick your tracing tool, connect it, sync
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>                      # open the browser Flow viewer
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
