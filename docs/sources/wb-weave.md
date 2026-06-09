# Weights & Biases — Weave

GigaFlow reads Weave calls via the W&B trace-server API. A template transform
(`wb_weave.yml`) ships, but you'll likely tailor its filter rules to your op names
(Weave has no structural span-type field).

## What you'll need
- A `WANDB_API_KEY` (wandb.ai → Settings → API keys).
- Your Weave project id as **`entity/project`** (e.g. `my-team/my-agent`).
- Base URL `https://trace.wandb.ai` (default; override for self-hosted).

## Connect

Run the setup wizard. The first time, it signs you in with your waitlist email
(same as `gigaflow login`), then walks you through the connection above:

```bash
gigaflow setup
```

Pick **W&B Weave** when prompted and enter your `entity/project` and `WANDB_API_KEY`.
The wizard creates a GigaFlow project, applies a transform, registers the
datasource, and runs the first sync — you never set an API key or backend URL by
hand.

## Transform

Weave calls normalize to nested dicts with `attributes.*`, `inputs`, `output`,
`op_name`, `display_name`. The bundled `wb_weave.yml` is a **template** — verify
the classification preview the wizard shows, and if your op names don't match,
copy the template, adjust the filter rules, and give the wizard the path to your
edited file when it asks for a transform.

## After the first sync

```bash
gigaflow sync                                    # re-pull new traces anytime
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
