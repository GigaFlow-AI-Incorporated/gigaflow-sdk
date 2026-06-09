# The `gigaflow.env` file

`gigaflow.env` is an **optional** convenience file that pre-fills the answers to
`gigaflow setup`. You never need it: running `gigaflow setup` and choosing
**"Enter values interactively"** walks you through every value. Use a
`gigaflow.env` when you want a repeatable, checked-in (secrets excluded!) setup —
common for dev environments and CI.

## How it's used

- `gigaflow setup` → option **2) Load from a gigaflow.env file** prompts for its path.
- The CLI also auto-loads a `gigaflow.env` in the current directory at startup,
  injecting any keys into the environment **without** overriding variables you've
  already exported.

It's a standard `.env` file: `KEY=value` per line, `#` comments, blank lines
ignored, optional quotes around values.

## GigaFlow core

| Key | Purpose |
| --- | --- |
| `GIGAFLOW_PROJECT_NAME` | Default project name suggested during setup. A project is a namespace grouping your traces and evals. |
| `GIGAFLOW_TRANSFORM_YML` | Path to a custom `transform.yml` (otherwise the built-in per-vendor transform is used). |
| `OPENAI_API_KEY` | Used by `gigaflow compute` for Flow analysis. |

## Developer overrides

These are for local/self-hosted development only — hosted users don't set them.
The backend defaults to `https://api.gigaflow.io/api/v1`, and authentication is
handled by `gigaflow login`.

| Key | Purpose |
| --- | --- |
| `GIGAFLOW_BACKEND_URL` | Point the CLI at a non-default backend (e.g. `http://localhost:8000/api/v1`). Same as `--backend`. |
| `GIGAFLOW_API_KEY` | Static bearer key, bypassing interactive login. Same as `--api-key`. |

## Per-vendor connection details

Only the section for the tracing tool you connect is needed. See each vendor's
[setup guide](sources/README.md) for where to find these values.

### Arize Phoenix (Postgres)

| Key | Default |
| --- | --- |
| `GIGAFLOW_DB_HOST` | `host.docker.internal` |
| `GIGAFLOW_DB_PORT` | (required) |
| `GIGAFLOW_DB_USER` | `postgres` |
| `GIGAFLOW_DB_PASSWORD` | (prompted) |
| `GIGAFLOW_DB_NAME` | `postgres` |
| `GIGAFLOW_DB_TABLE` | `spans` |

### Braintrust

| Key | Default |
| --- | --- |
| `BRAINTRUST_API_URL` | `https://api.braintrust.dev` |
| `BRAINTRUST_PROJECT` | (your project name) |
| `BRAINTRUST_API_KEY` | (required) |

### Logfire

| Key | Default |
| --- | --- |
| `LOGFIRE_API_BASE` | `https://logfire-us.pydantic.dev` |
| `LOGFIRE_READ_TOKEN` | (required) |

### MLflow

| Key | Default |
| --- | --- |
| `MLFLOW_TRACKING_URI` | (required) |
| `MLFLOW_TRACKING_TOKEN` | (optional) |

### W&B Weave

| Key | Default |
| --- | --- |
| `WEAVE_TRACE_SERVER` | `https://trace.wandb.ai` |
| `WEAVE_PROJECT` | `<entity>/<project>` |
| `WANDB_API_KEY` | (required) |

## Example

```bash
# gigaflow.env — Braintrust dev setup
GIGAFLOW_PROJECT_NAME=checkout-bot
BRAINTRUST_PROJECT=checkout-bot
BRAINTRUST_API_KEY=sk-...
```
