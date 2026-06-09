# Arize Phoenix

GigaFlow reads Phoenix's `spans` table over a direct Postgres connection. A
bundled transform (`arize_phoenix.yml`) handles standard OpenInference spans out
of the box.

## What you'll need
- A Phoenix Postgres instance reachable from the GigaFlow backend, and its
  connection details: host, port, user, password, database.
- The table name (default `spans`).

## Connect

Run the setup wizard. The first time, it signs you in with your waitlist email
(same as `gigaflow login`), then walks you through the connection above:

```bash
gigaflow setup
```

Pick **Arize Phoenix** when prompted and enter your Postgres connection and table
name. The wizard creates a GigaFlow project, applies the bundled
`arize_phoenix.yml` transform, registers the datasource, and runs the first
sync — you never set an API key or backend URL by hand.

## Transform

The bundled `arize_phoenix.yml` maps OpenInference `span_kind` + `attributes.*`.
If your Phoenix uses non-standard attribute paths, copy it, edit, and give the
wizard the path to your edited file when it asks for a transform (leave the prompt
blank to use the bundled one).

## After the first sync

```bash
gigaflow sync                                    # re-pull new traces anytime
gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
gigaflow inspect <trace_id>
```
