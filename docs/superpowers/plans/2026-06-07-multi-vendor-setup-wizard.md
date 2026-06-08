# Multi-vendor setup wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gigaflow setup` ask which tracing vendor the user has and branch accordingly — supporting all five backend source types, shipping best-effort generic transforms for four of them, and previewing span classification before finishing.

**Architecture:** Introduce a vendor-strategy registry in `gigaflow/_setup.py` (one `VendorSpec` per source type). `run_wizard()` becomes: backend → pick vendor → vendor-specific connection prompts → project (name auto-suggested from the vendor project) → transform (built-in or supplied) → register (now sending `source_type` + `api_key`) → sync → post-sync classification preview with a re-prompt-on-poor-result loop. New bundled transforms (`braintrust.yml`, `mlflow.yml`, `wb_weave.yml`) classify on each vendor's structural span-type field where one exists.

**Tech Stack:** Python 3.12, stdlib only (no external deps — the CLI never parses YAML; transforms are uploaded as raw text and parsed by the backend). Tests run the CLI as a subprocess against an in-process mock HTTP server (`tests/conftest.py`).

**Scope decisions (resolved from the spec's open questions):**
- **Preview = sync-then-inspect (v1).** CLI-only, single repo, single PR. The cleaner pre-commit *dry-run* endpoint (backend repo) is deferred — Task 9 files it as a GitHub issue.
- **W&B Weave = bundled selectable template** `transforms/wb_weave.yml` (convention-based, heavily commented).
- The CLI cannot import the backend `TransformConfig`/transformer (zero-dep + separate repo), so transform *content* is validated by structural substring checks here; full parse+classification validation against fixtures is filed as a backend follow-up (Task 9).

---

## File Structure

`gigaflow-sdk`:
- `gigaflow/_setup.py` — **modified.** Add `VendorSpec` + `VENDORS` registry, `_pick_vendor()`, per-vendor `collect_*()` connection functions, `_classification_summary()` + preview loop; rewrite `run_wizard()` to the branched flow; `register_datasource()` gains `source_type`/`api_key`/`ui_base_url`.
- `gigaflow/transforms/braintrust.yml` — **new.** Generic, classifies on `span_attributes.type`.
- `gigaflow/transforms/mlflow.yml` — **new.** Generic, classifies on `attributes.mlflow.spanType`.
- `gigaflow/transforms/wb_weave.yml` — **new.** Template, classifies on span-name convention.
- `gigaflow/commands/setup.py` — **modified.** Vendor-neutral help text.
- `tests/test_setup_wizard_vendors.py` — **new.** Per-vendor wizard tests + preview-loop tests.
- `tests/test_commands.py` — **modified.** Update existing `TestSetup` stdin sequences for the new vendor-pick prompt + reordered flow.
- `tests/conftest.py` — **modified.** Mock handler: echo `source_type` on datasource create; add a knob to return an "all unclassified" spans payload for the poor-classification test.
- `CLAUDE.md`, `README.md` — **modified.** Document multi-vendor setup.

---

## Background the engineer needs

**Current wizard (`gigaflow/_setup.py::run_wizard`)** prompts in this order today:
env-file path → backend URL → API key → project name → transform path → Postgres host/port/user/password/db/table → then `create_project` → `upload_transform` → `register_datasource` → `do_sync` → `_show_span_preview`.

**`register_datasource` today** (no `source_type`, so everything is created as `arize_phoenix`):
```python
def register_datasource(base_url, project_id, connection_url, source_table, api_key=None):
    status, resp = api(base_url, "POST", "/datasources/", {
        "project_id": project_id,
        "name": "arize-phoenix",
        "connection_url": connection_url,
        "source_table": source_table,
    }, api_key=_resolve_key(api_key))
    ...
```

**Backend `DataSourceCreate` fields:** `project_id, name, connection_url, source_table (default "spans"), source_type (default "arize_phoenix"), api_key, ui_base_url`. The backend auto-discovers `ui_base_url` for HTTP vendors when omitted, so the CLI does **not** need to send it.

**`_fmt` helpers:** `header(t)`, `section(t)`, `ok(m)`, `fail(m)`, `info(m)`, `prompt(label, default="", required=False) -> str`, `prompt_password(label) -> str`, `table(rows, headers)`.

**`_show_span_preview(base_url, project_id, api_key)`** already fetches the first trace's spans and counts `primitive_type`. Task 5 refactors its counting into a reusable `_classification_summary`.

**Test harness:** `tests/test_commands.py::run(args, env, stdin=b"...")` runs the CLI as a subprocess; prompts are answered by newline-separated stdin. `tests/conftest.py::_MockAPIHandler` mocks the backend. Constants in `tests/_constants.py` (`MOCK_PROJECT_ID`, `MOCK_DATASOURCE_ID`, `MOCK_TRACE_ID`). Run tests with `uv run pytest`.

**New uniform prompt order (all vendors):**
1. env-file path
2. backend URL
3. API key
4. **vendor pick** (1–5; blank → 1 Arize Phoenix, for back-compat)
5. vendor connection prompts (Arize: host/port/user/pw/db/table → builds `postgresql://`; HTTP vendors: API base [default] + identifier + key)
6. project name (default = vendor project name if the vendor supplied one, else vendor default)
7. transform path (blank → vendor built-in)
8. (automatic) register → sync → preview → confirm/fix

---

### Task 1: Vendor registry data structure

**Files:**
- Modify: `gigaflow/_setup.py` (add near the top, after imports)
- Test: `tests/test_setup_wizard_vendors.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_wizard_vendors.py
"""Unit tests for the vendor registry and per-vendor wizard branches."""
from gigaflow import _setup


def test_vendor_registry_has_all_five():
    keys = [v.key for v in _setup.VENDORS]
    assert keys == ["arize_phoenix", "braintrust", "logfire", "mlflow", "wb_weave"]


def test_vendor_lookup_by_choice_number():
    # 1-indexed menu choice → VendorSpec
    assert _setup.vendor_by_choice("1").key == "arize_phoenix"
    assert _setup.vendor_by_choice("2").key == "braintrust"
    assert _setup.vendor_by_choice("5").key == "wb_weave"


def test_vendor_lookup_blank_defaults_to_arize():
    assert _setup.vendor_by_choice("").key == "arize_phoenix"


def test_vendor_lookup_invalid_returns_none():
    assert _setup.vendor_by_choice("9") is None
    assert _setup.vendor_by_choice("banana") is None


def test_each_vendor_declares_a_transform_name():
    # Every vendor maps to a bundled transform file name.
    for v in _setup.VENDORS:
        assert v.transform_file.endswith(".yml")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -v`
Expected: FAIL — `AttributeError: module 'gigaflow._setup' has no attribute 'VENDORS'`

- [ ] **Step 3: Write minimal implementation**

Add to `gigaflow/_setup.py` after the imports block:

```python
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class VendorSpec:
    key: str            # backend source_type
    label: str          # menu label
    transform_file: str  # bundled transform filename in gigaflow/transforms/
    # collect(env) -> dict with keys:
    #   connection_url, source_table, api_key (str|None),
    #   vendor_project_name (str|None — used to default the GigaFlow project name)
    collect: Callable[[dict], dict]


# Connection-collection functions are defined in Task 4; placeholder names are
# bound here once those exist. For Task 1, use a temporary lambda so the registry
# is importable; Task 4 replaces these with real collectors.
def _todo_collect(env: dict) -> dict:  # replaced in Task 4
    raise NotImplementedError


VENDORS: list[VendorSpec] = [
    VendorSpec("arize_phoenix", "Arize Phoenix   (Postgres)",   "arize_phoenix.yml", _todo_collect),
    VendorSpec("braintrust",    "Braintrust      (REST API)",   "braintrust.yml",    _todo_collect),
    VendorSpec("logfire",       "Logfire         (REST API)",   "logfire.yml",       _todo_collect),
    VendorSpec("mlflow",        "MLflow          (REST API)",   "mlflow.yml",        _todo_collect),
    VendorSpec("wb_weave",      "W&B Weave       (REST API)",   "wb_weave.yml",      _todo_collect),
]


def vendor_by_choice(choice: str) -> Optional[VendorSpec]:
    """Map a 1-indexed menu string to a VendorSpec. Blank → Arize Phoenix."""
    choice = (choice or "").strip()
    if choice == "":
        return VENDORS[0]
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(VENDORS):
            return VENDORS[idx]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add gigaflow/_setup.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): add vendor registry skeleton"
```

---

### Task 2: Bundled transforms for Braintrust, MLflow, W&B Weave

**Files:**
- Create: `gigaflow/transforms/braintrust.yml`
- Create: `gigaflow/transforms/mlflow.yml`
- Create: `gigaflow/transforms/wb_weave.yml`
- Test: `tests/test_setup_wizard_vendors.py` (append)

These are uploaded as raw text; the backend parses them. Field paths derive from
the readers (`braintrust_reader.py`, `mlflow_reader.py`, `wb_weave_reader.py`) and
the example transforms in the `gigaflow` repo.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_wizard_vendors.py`:

```python
import importlib.resources


def _read_transform(name: str) -> str:
    return importlib.resources.files("gigaflow.transforms").joinpath(name).read_text()


def test_braintrust_transform_classifies_on_span_type():
    text = _read_transform("braintrust.yml")
    assert "source:" in text and "braintrust" in text
    assert "span_attributes.type" in text          # structural classifier
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text


def test_mlflow_transform_classifies_on_spantype():
    text = _read_transform("mlflow.yml")
    assert "mlflow" in text
    assert "attributes.mlflow.spanType" in text     # structural classifier
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text


def test_wb_weave_transform_is_template_with_span_name_filter():
    text = _read_transform("wb_weave.yml")
    assert "wb_weave" in text
    assert "span_name" in text                       # convention-based
    assert "TEMPLATE" in text                         # flagged as needing edits
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k transform -v`
Expected: FAIL — `FileNotFoundError` / resource missing for `braintrust.yml`

- [ ] **Step 3: Create the transform files**

`gigaflow/transforms/braintrust.yml`:
```yaml
# Gigaflow built-in transform for Braintrust (REST API source).
#
# Classifies on `span_attributes.type`, which the Braintrust SDK sets via
# start_span(type=...) and auto-instrumentation populates ("llm"/"tool"/...).
# This is structural — it does NOT depend on how you named your spans.
#
# Braintrust events expose top-level `input`/`output`, a `metadata` bag (where
# OTel gen_ai.* keys land if your instrumentation emits them), and a `metrics`
# bag for token counts. If your spans don't set `type`, edit the filters below
# or supply your own transform.yml.
version: "1"
source: "braintrust"

primitives:
  user_input:
    filter:
      field: "span_attributes.type"
      value: ["function", "task"]
      mode: "exact"
    mapping:
      content: "input"
      message: "input"

  llm_call:
    filter:
      field: "span_attributes.type"
      value: "llm"
      mode: "exact"
    mapping:
      model:             "metadata.gen_ai.request.model"
      provider:          "metadata.gen_ai.system"
      input:             "input"
      completion:        "output"
      prompt_tokens:     "metrics.prompt_tokens"
      completion_tokens: "metrics.completion_tokens"

  tool_invocation:
    filter:
      field: "span_attributes.type"
      value: "tool"
      mode: "exact"
    mapping:
      tool_name:   "span_attributes.name"
      tool_input:  "input"
      tool_output: "output"
```

`gigaflow/transforms/mlflow.yml`:
```yaml
# Gigaflow built-in transform for MLflow (REST API source).
#
# Classifies on `attributes.mlflow.spanType`, the MLflow SpanType
# (LLM/TOOL/AGENT/CHAIN/RETRIEVER) exported as a span attribute. Structural —
# independent of span names. MLflow stores call IO under
# `mlflow.spanInputs` / `mlflow.spanOutputs`; gen_ai.* attributes appear when
# your instrumentation sets them.
version: "1"
source: "mlflow"

primitives:
  user_input:
    filter:
      field: "attributes.mlflow.spanType"
      value: "AGENT"
      mode: "exact"
    mapping:
      content: "attributes.mlflow.spanInputs"

  llm_call:
    filter:
      field: "attributes.mlflow.spanType"
      value: ["LLM", "CHAT_MODEL"]
      mode: "exact"
    mapping:
      model:             "attributes.gen_ai.request.model"
      provider:          "attributes.gen_ai.system"
      input:             "attributes.mlflow.spanInputs"
      completion:        "attributes.mlflow.spanOutputs"
      prompt_tokens:     "attributes.gen_ai.usage.input_tokens"
      completion_tokens: "attributes.gen_ai.usage.output_tokens"

  tool_invocation:
    filter:
      field: "attributes.mlflow.spanType"
      value: ["TOOL", "RETRIEVER"]
      mode: "exact"
    mapping:
      tool_name:   "attributes.gen_ai.tool.name"
      tool_input:  "attributes.mlflow.spanInputs"
      tool_output: "attributes.mlflow.spanOutputs"
```

`gigaflow/transforms/wb_weave.yml`:
```yaml
# Gigaflow TEMPLATE transform for W&B Weave (REST API source).
#
# Weave has NO structural span-type field — a span's identity is its op/function
# name. This template classifies on span_name with common conventions; you will
# likely need to edit the `value` lists below to match YOUR op names. The setup
# wizard previews classification so you can see whether these defaults matched.
#
# Weave calls expose top-level `inputs` / `output`; token usage (if present)
# lives under `summary.usage.*`; gen_ai.* attributes appear only if your
# instrumentation set them.
version: "1"
source: "wb_weave"

primitives:
  user_input:
    filter:
      field: "span_name"
      value: ["agent run", "agent", "run"]
      mode: "prefix"
    mapping:
      content: "inputs"
      message: "inputs"

  llm_call:
    filter:
      field: "span_name"
      value: ["chat", "llm", "completion", "openai", "anthropic"]
      mode: "prefix"
    mapping:
      model:             "attributes.gen_ai.request.model"
      input:             "inputs"
      completion:        "output"
      prompt_tokens:     "summary.usage.prompt_tokens"
      completion_tokens: "summary.usage.completion_tokens"

  tool_invocation:
    filter:
      field: "span_name"
      value: ["tool", "running tool"]
      mode: "prefix"
    mapping:
      tool_name:   "attributes.gen_ai.tool.name"
      tool_input:  "inputs"
      tool_output: "output"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k transform -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Verify the files ship as package data**

`pyproject.toml` already declares `"gigaflow.transforms" = ["*.yml"]`. Confirm:

Run: `grep -n 'gigaflow.transforms' pyproject.toml`
Expected: a line including `["*.yml"]` (no edit needed — new `.yml` files are included by the glob).

- [ ] **Step 6: Commit**

```bash
git add gigaflow/transforms/braintrust.yml gigaflow/transforms/mlflow.yml gigaflow/transforms/wb_weave.yml tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): bundle best-effort transforms for braintrust/mlflow/wb_weave"
```

---

### Task 3: `register_datasource` sends `source_type` and `api_key`

**Files:**
- Modify: `gigaflow/_setup.py` (`register_datasource`)
- Modify: `tests/conftest.py` (echo `source_type` back on create so tests can assert it)
- Test: `tests/test_setup_wizard_vendors.py` (append)

- [ ] **Step 1: Make the mock echo `source_type`**

In `tests/conftest.py`, the `do_POST` branch for `/api/v1/datasources/` currently returns a fixed body. Capture and echo the posted `source_type`:

```python
        elif p == "/api/v1/datasources/":
            body = self._read_json()                       # add if not already read
            _MockAPIHandler.last_datasource_source_type = (body or {}).get("source_type")
            _MockAPIHandler.last_datasource_api_key = (body or {}).get("api_key")
            self._ok({"datasource_id": MOCK_DATASOURCE_ID})
```

Add class attributes near the top of `_MockAPIHandler`:
```python
    last_datasource_source_type = None
    last_datasource_api_key = None
```
(Use the handler's existing JSON-body reader; if none exists, read `self.rfile.read(int(self.headers["Content-Length"]))` and `json.loads` it.)

- [ ] **Step 2: Write the failing test**

Append to `tests/test_setup_wizard_vendors.py`:

```python
from gigaflow import _setup as setup_mod


def test_register_datasource_sends_source_type_and_api_key(monkeypatch):
    captured = {}

    def fake_api(base_url, method, path, body=None, **kw):
        captured["path"] = path
        captured["body"] = body
        captured["api_key"] = kw.get("api_key")
        return 200, {"datasource_id": "ds-1"}

    monkeypatch.setattr(setup_mod, "api", fake_api)
    ds = setup_mod.register_datasource(
        "http://x/api/v1", "proj-1",
        connection_url="https://api.braintrust.dev",
        source_table="my-proj",
        api_key="bt-key",
        source_type="braintrust",
        name="braintrust",
    )
    assert ds == "ds-1"
    assert captured["body"]["source_type"] == "braintrust"
    assert captured["body"]["api_key"] == "bt-key"
    assert captured["body"]["source_table"] == "my-proj"
    assert captured["body"]["name"] == "braintrust"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k register_datasource -v`
Expected: FAIL — `TypeError: register_datasource() got an unexpected keyword argument 'source_type'`

- [ ] **Step 4: Update `register_datasource`**

Replace the function in `gigaflow/_setup.py`:

```python
def register_datasource(base_url, project_id, connection_url, source_table,
                        api_key=None, source_type="arize_phoenix", name=None):
    payload = {
        "project_id": project_id,
        "name": name or source_type,
        "connection_url": connection_url,
        "source_table": source_table,
        "source_type": source_type,
    }
    if api_key:
        payload["api_key"] = api_key
    status, resp = api(base_url, "POST", "/datasources/", payload, api_key=_resolve_key(api_key))
    if status != 200:
        _fmt.fail(f"Failed to register datasource ({status}): {resp}")
        return None
    datasource_id = resp["datasource_id"]
    _fmt.ok("Datasource registered")
    _fmt.info(f"datasource_id: {datasource_id}")
    return datasource_id
```

Note: `api_key` is sent both in the body (the vendor token the backend uses to
fetch) and as the bearer (`_resolve_key` → GigaFlow auth). For Arize Phoenix
`api_key` is `None`, so neither the body field nor a vendor bearer is added.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k register_datasource -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add gigaflow/_setup.py tests/conftest.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): register_datasource sends source_type + api_key"
```

---

### Task 4: Per-vendor connection collectors + vendor picker

**Files:**
- Modify: `gigaflow/_setup.py` (add collectors, `_pick_vendor`, bind into `VENDORS`)
- Test: `tests/test_setup_wizard_vendors.py` (append)

Collectors are pure prompt sequences returning a normalized dict. They take the
parsed `env` dict (for `gigaflow.env` pre-fill, matching today's behavior).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_wizard_vendors.py`. Drive the collectors by monkeypatching `_fmt.prompt`/`_fmt.prompt_password` with a scripted queue:

```python
class _Prompts:
    """Feed scripted answers to _fmt.prompt / prompt_password in order."""
    def __init__(self, answers):
        self.answers = list(answers)
    def prompt(self, label, default="", required=False):
        return self.answers.pop(0) if self.answers else default
    def prompt_password(self, label):
        return self.answers.pop(0) if self.answers else ""


def _install_prompts(monkeypatch, answers):
    p = _Prompts(answers)
    monkeypatch.setattr(setup_mod._fmt, "prompt", p.prompt)
    monkeypatch.setattr(setup_mod._fmt, "prompt_password", p.prompt_password)


def test_collect_braintrust(monkeypatch):
    # answers: api base (blank → default), project name, api key
    _install_prompts(monkeypatch, ["", "my-bt-proj", "bt-secret"])
    out = setup_mod.collect_braintrust({})
    assert out["connection_url"] == "https://api.braintrust.dev"
    assert out["source_table"] == "my-bt-proj"
    assert out["api_key"] == "bt-secret"
    assert out["vendor_project_name"] == "my-bt-proj"


def test_collect_wb_weave(monkeypatch):
    _install_prompts(monkeypatch, ["", "my-org/rag-eval", "wandb-key"])
    out = setup_mod.collect_wb_weave({})
    assert out["connection_url"] == "https://trace.wandb.ai"
    assert out["source_table"] == "my-org/rag-eval"
    assert out["api_key"] == "wandb-key"
    assert out["vendor_project_name"] == "my-org/rag-eval"


def test_collect_logfire_has_no_vendor_project(monkeypatch):
    _install_prompts(monkeypatch, ["", "logfire-read-token"])
    out = setup_mod.collect_logfire({})
    assert out["connection_url"] == "https://logfire-us.pydantic.dev"
    assert out["api_key"] == "logfire-read-token"
    assert out["vendor_project_name"] is None


def test_collect_arize_builds_postgres_url(monkeypatch):
    # host, port, user, password, db, table
    _install_prompts(monkeypatch, ["host.docker.internal", "5432", "postgres", "pw", "postgres", "spans"])
    out = setup_mod.collect_arize_phoenix({})
    assert out["connection_url"] == "postgresql://postgres:pw@host.docker.internal:5432/postgres"
    assert out["source_table"] == "spans"
    assert out["api_key"] is None
    assert out["vendor_project_name"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k collect -v`
Expected: FAIL — `AttributeError: module 'gigaflow._setup' has no attribute 'collect_braintrust'`

- [ ] **Step 3: Implement collectors and bind them**

Add to `gigaflow/_setup.py`:

```python
def collect_arize_phoenix(env: dict) -> dict:
    _fmt.section("Connection: Arize Phoenix database")
    print()
    print("  Enter the PostgreSQL connection Arize Phoenix writes to.")
    print("  Tip: if GigaFlow runs in Docker, use 'host.docker.internal'.")
    print()
    host  = _fmt.prompt("Host", env.get("GIGAFLOW_DB_HOST", "host.docker.internal"))
    port  = _fmt.prompt("Port", env.get("GIGAFLOW_DB_PORT", ""), required=True)
    user  = _fmt.prompt("User", env.get("GIGAFLOW_DB_USER", "postgres"))
    if env.get("GIGAFLOW_DB_PASSWORD"):
        password = env["GIGAFLOW_DB_PASSWORD"]
        _fmt.info("Password: [from env file]")
    else:
        password = _fmt.prompt_password("Password")
    db    = _fmt.prompt("Database", env.get("GIGAFLOW_DB_NAME", "postgres"))
    table = _fmt.prompt("Source table", env.get("GIGAFLOW_DB_TABLE", "spans"))
    return {
        "connection_url": f"postgresql://{user}:{password}@{host}:{port}/{db}",
        "source_table": table,
        "api_key": None,
        "vendor_project_name": None,
    }


def _collect_http_vendor(env, *, title, default_url, url_env, key_env,
                         identifier_label=None, identifier_env=None,
                         key_required=True):
    _fmt.section(f"Connection: {title}")
    url = _fmt.prompt("API base URL", env.get(url_env, default_url)).rstrip("/")
    identifier = None
    if identifier_label:
        identifier = _fmt.prompt(identifier_label, env.get(identifier_env, "")) or None
    default_key = env.get(key_env, "")
    key = _fmt.prompt(f"API key{'' if key_required else ' (optional)'}", default_key) or None
    return {
        "connection_url": url,
        "source_table": identifier or "spans",
        "api_key": key,
        "vendor_project_name": identifier,
    }


def collect_braintrust(env: dict) -> dict:
    return _collect_http_vendor(
        env, title="Braintrust", default_url="https://api.braintrust.dev",
        url_env="BRAINTRUST_API_URL", key_env="BRAINTRUST_API_KEY",
        identifier_label="Braintrust project name", identifier_env="BRAINTRUST_PROJECT",
    )


def collect_logfire(env: dict) -> dict:
    return _collect_http_vendor(
        env, title="Logfire", default_url="https://logfire-us.pydantic.dev",
        url_env="LOGFIRE_API_BASE", key_env="LOGFIRE_READ_TOKEN",
    )


def collect_mlflow(env: dict) -> dict:
    return _collect_http_vendor(
        env, title="MLflow", default_url="",
        url_env="MLFLOW_TRACKING_URI", key_env="MLFLOW_TRACKING_TOKEN",
        key_required=False,
    )


def collect_wb_weave(env: dict) -> dict:
    return _collect_http_vendor(
        env, title="W&B Weave", default_url="https://trace.wandb.ai",
        url_env="WEAVE_TRACE_SERVER", key_env="WANDB_API_KEY",
        identifier_label="Weave project (<entity>/<project>)", identifier_env="WEAVE_PROJECT",
    )


_COLLECTORS = {
    "arize_phoenix": collect_arize_phoenix,
    "braintrust": collect_braintrust,
    "logfire": collect_logfire,
    "mlflow": collect_mlflow,
    "wb_weave": collect_wb_weave,
}
```

Replace the `VENDORS` list's `_todo_collect` entries so each `collect` points at
the matching function (rebuild the list after `_COLLECTORS` is defined):

```python
VENDORS = [
    VendorSpec(v.key, v.label, v.transform_file, _COLLECTORS[v.key])
    for v in VENDORS
]
```

Add the picker:

```python
def _pick_vendor() -> Optional[VendorSpec]:
    _fmt.section("Step 2: Tracing tool")
    print()
    print("  Which tracing tool are you using?")
    for i, v in enumerate(VENDORS, 1):
        print(f"    {i}) {v.label}")
    print()
    choice = _fmt.prompt("Choice", "1")
    vendor = vendor_by_choice(choice)
    if vendor is None:
        _fmt.fail(f"Unknown choice: {choice!r}")
    return vendor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k collect -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the whole new test file**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -v`
Expected: PASS (all tasks 1–4 tests)

- [ ] **Step 6: Commit**

```bash
git add gigaflow/_setup.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): per-vendor connection collectors + vendor picker"
```

---

### Task 5: Classification summary + preview/confirm loop

**Files:**
- Modify: `gigaflow/_setup.py` (`_classification_summary`, `_preview_and_confirm`)
- Modify: `tests/conftest.py` (knob to serve an all-unclassified spans payload)
- Test: `tests/test_setup_wizard_vendors.py` (append)

`_classification_summary(spans)` returns `(counts: dict, unclassified: int)`.
`_preview_and_confirm(...)` prints the summary; if classification is poor (zero
classified spans) it warns and returns False so the caller can offer a fix.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_wizard_vendors.py`:

```python
def test_classification_summary_counts_primitives():
    spans = [
        {"primitive_type": "llm_call"},
        {"primitive_type": "llm_call"},
        {"primitive_type": "tool_invocation"},
        {"primitive_type": None},
        {},  # no primitive_type
    ]
    counts, unclassified = setup_mod._classification_summary(spans)
    assert counts["llm_call"] == 2
    assert counts["tool_invocation"] == 1
    assert unclassified == 2


def test_classification_summary_all_unclassified():
    spans = [{"primitive_type": None}, {}]
    counts, unclassified = setup_mod._classification_summary(spans)
    assert sum(counts.values()) == 0
    assert unclassified == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k classification_summary -v`
Expected: FAIL — `AttributeError: ... has no attribute '_classification_summary'`

- [ ] **Step 3: Implement the summary + preview helpers**

Add to `gigaflow/_setup.py`:

```python
_PRIMITIVES = ("llm_call", "tool_invocation", "user_input", "transform")


def _classification_summary(spans: list) -> tuple[dict, int]:
    counts = {p: 0 for p in _PRIMITIVES}
    unclassified = 0
    for s in spans:
        pt = s.get("primitive_type")
        if pt in counts:
            counts[pt] += 1
        else:
            unclassified += 1
    return counts, unclassified


def _fetch_sample_spans(base_url, project_id, api_key):
    status, resp = api(base_url, "GET", f"/traces/?project_id={project_id}",
                       api_key=_resolve_key(api_key))
    if status != 200:
        return []
    traces = resp.get("traces", [])
    if not traces:
        return []
    trace_id = traces[0]["trace_id"]
    status, resp = api(base_url, "GET", f"/traces/{trace_id}/spans",
                       api_key=_resolve_key(api_key))
    if status != 200:
        return []
    return resp if isinstance(resp, list) else resp.get("spans", [])


def _preview_and_confirm(base_url, project_id, api_key) -> bool:
    """Show how a sample of the user's spans classified. Returns True if it looks
    OK (or there's nothing to preview), False if classification looks broken."""
    spans = _fetch_sample_spans(base_url, project_id, api_key)
    if not spans:
        return True  # nothing synced yet / preview unavailable — don't block
    counts, unclassified = _classification_summary(spans)
    classified = sum(counts.values())
    _fmt.section("Classification preview")
    summary = " · ".join(f"{n} {p}" for p, n in counts.items() if n)
    _fmt.info(f"{len(spans)} spans sampled → {summary or '0 classified'} · {unclassified} unmatched")
    if classified == 0:
        _fmt.fail("None of your spans matched the transform.")
        observed = sorted({s.get("span_name", "?") for s in spans})[:8]
        _fmt.info("Span names seen: " + ", ".join(observed))
        return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_wizard_vendors.py -k classification_summary -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the conftest knob for the poor-classification e2e**

In `tests/conftest.py`, make the `/traces/{id}/spans` GET branch honor an env
flag so an e2e test can simulate "nothing classified":

```python
        elif p == f"/api/v1/traces/{MOCK_TRACE_ID}/spans":
            if os.environ.get("MOCK_ALL_UNCLASSIFIED") == "1":
                self._ok([{"span_name": "weird-op", "primitive_type": None},
                          {"span_name": "other-op", "primitive_type": None}])
            else:
                self._ok([... existing classified sample ...])  # keep current body
```
(Read `os` is already imported in conftest; if not, add `import os`.)

- [ ] **Step 6: Commit**

```bash
git add gigaflow/_setup.py tests/conftest.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): span classification preview helpers"
```

---

### Task 6: Rewrite `run_wizard` to the branched, uniform-order flow

**Files:**
- Modify: `gigaflow/_setup.py` (`run_wizard`)
- Test: covered by Task 7 e2e tests

- [ ] **Step 1: Replace `run_wizard`**

```python
def run_wizard(base_url: str) -> dict | None:
    _fmt.header("GigaFlow Setup Wizard")

    env_path = _fmt.prompt("Path to gigaflow.env (leave blank to enter values manually)")
    env = load_env_file(env_path) if env_path else {}
    if env_path and env:
        _fmt.ok(f"Loaded env file: {env_path}")

    # Step 1: backend + key
    _fmt.section("Step 1: GigaFlow backend")
    base_url = _fmt.prompt("Backend base URL", env.get("GIGAFLOW_BACKEND_URL", base_url)).rstrip("/")
    default_key = env.get("GIGAFLOW_API_KEY", _config.get("api_key", "") or "")
    api_key = _fmt.prompt("GigaFlow API key (blank for none / local dev mode)", default_key) or None
    if not check_backend(base_url, api_key):
        return None

    # Step 2: vendor
    vendor = _pick_vendor()
    if vendor is None:
        return None

    # Step 3: connection (vendor-specific)
    conn = vendor.collect(env)

    # Step 4: project (auto-suggest name from the vendor project where present)
    _fmt.section("Step 4: Project")
    print()
    print("  GigaFlow groups your traces under a *project* (a container in GigaFlow).")
    print()
    suggested = conn.get("vendor_project_name") or env.get("GIGAFLOW_PROJECT_NAME") or f"{vendor.key}-project"
    project_name = _fmt.prompt("GigaFlow project name", suggested)
    project_id = create_project(base_url, project_name, api_key)
    if not project_id:
        return None

    # Step 5: transform (vendor built-in by default)
    transform_path = _fmt.prompt(
        f"Path to transform.yml (leave blank for built-in {vendor.label.split('(')[0].strip()} config)",
        env.get("GIGAFLOW_TRANSFORM_YML", ""),
    )
    if transform_path:
        try:
            with open(transform_path) as f:
                yaml_content = f.read()
            _fmt.ok(f"Loaded transform file: {transform_path}")
        except OSError as e:
            _fmt.fail(f"Could not read transform file: {e}")
            return None
    else:
        yaml_content = _load_transform(vendor.transform_file)
        _fmt.info(f"Using built-in {vendor.key} transform config")
        if vendor.key == "wb_weave":
            _fmt.info("Note: the W&B Weave transform is a TEMPLATE — verify the preview below.")
    if not upload_transform(base_url, project_id, yaml_content, api_key):
        return None

    # Step 6: register + sync + preview
    _fmt.section("Step 6: Register datasource & sync")
    datasource_id = register_datasource(
        base_url, project_id, conn["connection_url"], conn["source_table"],
        api_key=conn["api_key"], source_type=vendor.key, name=vendor.key,
    )
    if not datasource_id:
        return None
    result = do_sync(base_url, datasource_id, api_key)
    if result is None:
        return None

    synced_traces, _ = result
    if synced_traces > 0:
        ok = _preview_and_confirm(base_url, project_id, api_key)
        if not ok:
            _fmt.info("You can supply a custom transform and re-run:")
            _fmt.info("  gigaflow config clear  &&  gigaflow setup")
            _fmt.info("  (point the transform prompt at your own transform.yml)")

    config: dict = {"backend_url": base_url, "project_id": project_id, "datasource_id": datasource_id}
    if api_key:
        config["api_key"] = api_key
    _config.save(config)
    _fmt.ok(f"Configuration saved to {_config.CONFIG_PATH}")
    return config
```

Add the generalized transform loader (replacing the Arize-only `_load_default_transform`; keep `ARIZE_TRANSFORM_YAML` for back-compat if referenced elsewhere):

```python
def _load_transform(filename: str) -> str:
    ref = importlib.resources.files("gigaflow.transforms").joinpath(filename)
    return ref.read_text(encoding="utf-8")
```

Update `_load_default_transform` to delegate: `return _load_transform("arize_phoenix.yml")`.

- [ ] **Step 2: Lint**

Run: `uv run ruff check gigaflow/_setup.py`
Expected: no errors (fix imports/unused as needed).

- [ ] **Step 3: Commit**

```bash
git add gigaflow/_setup.py
git commit -m "feat(setup): branched multi-vendor wizard flow"
```

---

### Task 7: Update existing tests + add per-vendor e2e wizard tests

**Files:**
- Modify: `tests/test_commands.py` (`TestSetup` — new prompt order)
- Test: `tests/test_setup_wizard_vendors.py` (append e2e)

The new uniform order inserts a **vendor pick** prompt (step 4 overall) and moves
the Arize connection block to **after** backend/key/vendor but the project/
transform now come **after** connection. New Arize stdin order:
env-file, backend-url, api-key, **vendor(blank→Arize)**, host, port, user, password, db, table, **project name**, **transform path**.

- [ ] **Step 1: Update `test_fresh_setup_wizard`**

Replace its `stdin` and the prompt-order docstring:

```python
        # env, backend, key, vendor(blank=arize), host, port, user, pw, db, table, project, transform
        stdin = b"\n\n\n\n\nhost\n5432\n\ntestpass\n\n\n\n\n"
        result = run(["--backend", mock_server, "setup"], clean_env, stdin=stdin)
        assert result.returncode == 0, err(result)
        output = out(result)
        assert "Project created" in output
        assert "Datasource registered" in output
        assert "Sync complete" in output
        assert "Configuration saved" in output
```
(Drop the `"built-in Arize Phoenix"` assertion or change to `"built-in arize_phoenix"` to match the new info line.)

Note on counting: confirm the exact number of trailing blanks by running the test
and reading the prompt the wizard stops on; adjust blanks until it completes.

- [ ] **Step 2: Update the other two `TestSetup` tests similarly**

For `test_setup_wizard_custom_transform` and `test_setup_wizard_with_env_file`,
insert one blank for the vendor pick after the api-key answer and move the
project/transform answers to the end (after the Postgres block). Run each and
adjust blanks until green.

- [ ] **Step 3: Run the updated existing tests**

Run: `uv run pytest tests/test_commands.py::TestSetup -v`
Expected: PASS (all)

- [ ] **Step 4: Add a Braintrust e2e wizard test**

Append to `tests/test_setup_wizard_vendors.py`:

```python
import subprocess
from pathlib import Path
import json as _json
from _constants import GIGAFLOW, MOCK_PROJECT_ID, MOCK_DATASOURCE_ID


def _run(args, env, stdin=b"", timeout=15):
    import os
    return subprocess.run(GIGAFLOW + args, input=stdin, capture_output=True,
                          env=env, timeout=timeout, preexec_fn=os.setsid)


def test_braintrust_wizard_end_to_end(installed_cli, mock_server, clean_env):
    # env, backend, key, vendor=2 (braintrust), api base(blank), project name, api key,
    # gigaflow project name(blank→suggested), transform path(blank→built-in)
    stdin = b"\n\n\n2\n\nmy-bt-proj\nbt-secret\n\n\n"
    result = _run(["--backend", mock_server, "setup"], clean_env, stdin=stdin)
    assert result.returncode == 0, result.stderr.decode()
    out_s = result.stdout.decode()
    assert "Datasource registered" in out_s
    assert "Configuration saved" in out_s
    cfg = _json.loads((Path(clean_env["HOME"]) / ".gigaflow" / "config.json").read_text())
    assert cfg["project_id"] == MOCK_PROJECT_ID
    assert cfg["datasource_id"] == MOCK_DATASOURCE_ID
```

- [ ] **Step 5: Add the poor-classification fix-path test**

```python
def test_wizard_warns_when_nothing_classifies(installed_cli, mock_server, clean_env):
    import os
    env = dict(clean_env)
    env["MOCK_ALL_UNCLASSIFIED"] = "1"
    stdin = b"\n\n\n2\n\nmy-bt-proj\nbt-secret\n\n\n"
    result = _run(["--backend", mock_server, "setup"], env, stdin=stdin)
    assert result.returncode == 0, result.stderr.decode()
    out_s = result.stdout.decode()
    assert "None of your spans matched" in out_s
    assert "config clear" in out_s
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tests, including pre-existing)

- [ ] **Step 7: Commit**

```bash
git add tests/test_commands.py tests/test_setup_wizard_vendors.py
git commit -m "test(setup): multi-vendor wizard e2e + updated prompt order"
```

---

### Task 8: Vendor-neutral help text + docs

**Files:**
- Modify: `gigaflow/commands/setup.py`
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Update the subcommand help**

In `gigaflow/commands/setup.py`:
```python
    sub.add_parser("setup", help="Configure GigaFlow with a tracing datasource (Arize, Braintrust, Logfire, MLflow, W&B Weave)").set_defaults(func=_handle_setup)
```

- [ ] **Step 2: Update docs**

In `CLAUDE.md`, update the `setup` bullet to: "interactive first-run: pick your
tracing vendor (Arize Phoenix / Braintrust / Logfire / MLflow / W&B Weave),
enter its connection, register the datasource, upload a built-in or custom
transform, and sync — with a post-sync classification preview." Add a one-line
note that built-in transforms live in `gigaflow/transforms/` (one per vendor;
`wb_weave.yml` is a template).

In `README.md`, add a short "Supported tracing backends" list.

- [ ] **Step 3: Run the full suite once more**

Run: `uv run pytest -v && uv run ruff check .`
Expected: PASS, no lint errors.

- [ ] **Step 4: Commit**

```bash
git add gigaflow/commands/setup.py CLAUDE.md README.md
git commit -m "docs(setup): document multi-vendor setup"
```

---

### Task 9: File backend follow-ups as GitHub issues

**Files:** none (uses `gh`)

- [ ] **Step 1: File the dry-run preview enhancement**

```bash
gh issue create --repo GigaFlow-AI-Incorporated/gigaflow \
  --title "Pre-commit transform dry-run endpoint for setup wizard" \
  --body "The CLI setup wizard previews span classification *after* sync (append-only), so fixing a bad transform needs 'config clear' + redo. Add POST /api/v1/datasources/preview that fetches N raw spans via the vendor reader, applies a posted transform_yaml, and returns per-primitive counts + sample classifications without persisting — so the wizard can preview before registering. Definition of done: endpoint returns {counts, unmatched, samples, observed_span_names} for all five source_types; CLI _preview_and_confirm switched to call it pre-register."
```

- [ ] **Step 2: File the transform-fixture validation issue**

```bash
gh issue create --repo GigaFlow-AI-Incorporated/gigaflow \
  --title "Validate bundled braintrust/mlflow/wb_weave transforms against example fixtures" \
  --body "The CLI ships best-effort transforms (gigaflow-sdk gigaflow/transforms/{braintrust,mlflow,wb_weave}.yml). Add backend tests that load each via TransformConfig and assert they classify the matching examples/<vendor>/.../ fixture into the expected primitive counts. Confirm MLflow exports span type at attributes.mlflow.spanType. Definition of done: a backend test per vendor that fails if a field path drifts."
```

- [ ] **Step 3: Note completion**

No commit (issues only). Record the issue URLs in the PR description.

---

## Self-Review

**Spec coverage:**
- 5-vendor picker → Task 1 (`vendor_by_choice`) + Task 4 (`_pick_vendor`). ✓
- Per-vendor connection fields/defaults → Task 4 collectors. ✓
- `source_type` + `api_key` on register → Task 3. ✓
- Auto-suggested GigaFlow project name → Task 6 (`suggested` from `vendor_project_name`). ✓
- Generic transforms for Braintrust/MLflow + Weave template → Task 2. ✓
- Built-in vs custom transform + override → Task 6 transform step. ✓
- Interactive classification preview/confirm → Task 5 + Task 6 wiring + Task 7 e2e. ✓
- Vendor-neutral help text → Task 8. ✓
- Open questions resolved (preview = sync-then-inspect; Weave bundled template) → header + Task 9 defers dry-run. ✓

**Placeholder scan:** the `_todo_collect` in Task 1 is intentional scaffolding explicitly replaced in Task 4 (called out in both tasks), not a plan placeholder. The conftest "keep current body" note in Task 5 Step 5 refers to the existing mock body the engineer can see in the file. No "TBD"/"add error handling"/"write tests for the above" left.

**Type consistency:** `VendorSpec` fields (`key`, `label`, `transform_file`, `collect`) used consistently across Tasks 1/4/6. `collect(env) -> {connection_url, source_table, api_key, vendor_project_name}` shape is identical in Tasks 4/6. `register_datasource(..., api_key, source_type, name)` signature matches its call in Task 6. `_classification_summary -> (counts, unclassified)` consistent in Tasks 5/7. `_load_transform(filename)` defined in Task 6 and used for `vendor.transform_file`. ✓

**One known fragility (flagged, not a defect):** the exact count of blank lines in the e2e stdin sequences (Tasks 6/7) depends on the final prompt order; each test step says to run and adjust blanks until green rather than trusting the count blind.
