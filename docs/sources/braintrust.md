# Braintrust

GigaFlow pulls Braintrust **project logs** via the Braintrust REST API.

## What you'll need
- A **Braintrust API key** (Settings → API keys).
- Your **Braintrust project name** (exactly as it appears in Braintrust). The
  reader resolves it to the project UUID, then pages its logs.
- API base URL: `https://api.braintrust.dev` (default; override for EU/self-hosted).

## Connect

Run the setup wizard. The first time, it signs you in with your waitlist email
(same as `gigaflow login`), then walks you through the connection above:

```bash
gigaflow setup
```

Pick **Braintrust** when prompted and enter your project name and API key. The
wizard creates a GigaFlow project, applies a transform, registers the datasource,
and runs the first sync — you never set an API key or backend URL by hand.

## Transform

Leave the transform prompt blank to use the bundled `braintrust.yml`. To customise,
author a transform that maps Braintrust's normalized fields to GigaFlow primitives.
After the reader normalizes a Braintrust event, these dotted keys are available to
`mapping`: `input`, `output`, `metadata.*`, `metrics.*`, `span_attributes.*`, `name`.

Minimal sketch (adjust to your span shape):

```yaml
# braintrust.yml (illustrative)
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

Give the wizard the path to your edited file when it asks for a transform. To
iterate: run `gigaflow sync`, inspect the raw fields with `gigaflow spans <trace_id>`,
adjust the transform, and re-run setup/sync (sync is append-only + reclassifies).

## After the first sync

```bash
gigaflow sync                                    # re-pull new traces anytime
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```

## Notes
- The reader pages 1000 events/request (max 200 pages) and dedupes by event id.
- If `sync` returns `inserted: 0`, check the project name (must match exactly) and
  that the API key can read that project.
