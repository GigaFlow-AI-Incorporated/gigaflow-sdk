# Logfire (Pydantic)

GigaFlow queries Logfire's FusionFire Query API. A bundled transform
(`logfire.yml`) handles pydantic-ai/Logfire spans out of the box.

## What you'll need
- A Logfire **read token** (Logfire → project → Settings → Read tokens).
- Your project's API base, e.g. `https://logfire-us.pydantic.dev/<org>/<project>`
  (the org segment is your Logfire org/username slug).

## Connect

Run the setup wizard. The first time, it signs you in with your waitlist email
(same as `gigaflow login`), then walks you through the connection above:

```bash
gigaflow setup
```

Pick **Logfire** when prompted and paste in your API base and read token. The
wizard creates a GigaFlow project, applies the bundled `logfire.yml` transform,
registers the datasource, and runs the first sync — you never set an API key or
backend URL by hand.

> Optional: to restrict sync to a single service, set a service-name filter when
> prompted (Logfire is the only source that honours it).

## After the first sync

```bash
gigaflow sync                                    # re-pull new traces anytime
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
