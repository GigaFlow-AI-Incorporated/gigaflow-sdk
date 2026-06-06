# Transform config

> Preserved from the original README. A transform maps a source's raw spans to
> GigaFlow primitives. Per-source specifics live in [docs/sources/](sources/).


GigaFlow maps raw Arize Phoenix spans to its own primitives (`llm_call`, `tool_invocation`, `user_input`) using a YAML transform config.

The built-in config for Arize Phoenix is at:

```
gigaflow/transforms/arize_phoenix.yml
```

It maps the OpenInference span columns (`span_kind`, `attributes.*`) to the fields that Flow reads. If your Arize setup uses different attribute paths, copy the file, edit it, and provide the path during `gigaflow setup` when prompted:

```
Path to transform.yml (leave blank for built-in Arize Phoenix config): /path/to/my_transform.yml
```

You can also re-upload a transform config to an existing project without re-running the full wizard:

```bash
curl -X PUT $GIGAFLOW_BACKEND_URL/projects/<project_id>/transform \
  -H "Content-Type: text/plain" \
  --data-binary @my_transform.yml
```

After changing the transform config, re-sync to reclassify your spans:

```bash
gigaflow sync
```

Advanced: a `transform.yml` may also declare an optional top-level `auth_mappings` block that tags each tool-output atom with a per-atom Beta-distribution trust score, surfaced as the `authoritative_groundedness` trace metric. See [`gigaflow/README.md` → Authoritativeness mappings](gigaflow/README.md#authoritativeness-mappings-auth_mappings) for the full schema, the `when`-expression grammar, and worked examples for retrieval / HTTP / SQL tools.

### Transform config format

```yaml
version: "1.0"
source: arize_phoenix

primitives:
  llm_call:
    filter:
      field: span_kind        # top-level DB column
      value: "LLM"
    mapping:
      completion: attributes.output.value          # read by Flow for response atoms
      model: attributes.llm.model_name

  tool_invocation:
    filter:
      field: span_kind
      value: "TOOL"
    mapping:
      tool_output: attributes.output.value         # read by Flow for tool atoms
      tool_name: attributes.tool.name

  user_input:
    filter:
      field: span_kind
      value: "CHAIN"
    mapping:
      content: attributes.input.value              # read by Flow for the user query
```

Mapping values are dot-notation paths traversed against each span row. Nested JSON columns (e.g. `attributes`) are parsed automatically.

