# `gigaflow setup` Friction Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gigaflow setup` self-explanatory for first-time users: drop the bare gigaflow.env prompt, stop prompting for backend URL and API key, sign users in via the existing email login, and explain the project-name and vendor steps.

**Architecture:** Incremental modification of the existing argparse CLI + interactive wizard in `gigaflow/`. The default backend constant moves to `_config.py` so both `cli.py` and `_setup.py` can reference it without a circular import. Auth is resolved in the `setup` command handler via a new `ensure_authenticated()` that reuses the existing email login, then the resolved credential is passed into `run_wizard()`. The wizard loses its backend-URL and API-key prompts and gains an input-method choice plus explanatory copy.

**Tech Stack:** Python 3, argparse, pytest, MkDocs (Material).

> **Spec:** `docs/superpowers/specs/2026-06-08-setup-friction-fixes-design.md`
>
> **Correction vs spec:** the spec referenced a "browser loopback login (`run_loopback_login`)". The actual auth in this repo is **email-based waitlist login** — `gigaflow/_auth.py:login(base_url, email)` POSTs an email to `/auth/login` and stores a token. This plan reuses that real flow.

---

## File Structure

- `gigaflow/_config.py` — gains `DEFAULT_BACKEND_URL` (moved here from `cli.py`) so it's importable without cycles.
- `gigaflow/cli.py` — imports `DEFAULT_BACKEND_URL` from `_config` instead of defining it.
- `gigaflow/commands/auth.py` — gains `interactive_login(base_url) -> bool` (extracted from `_handle_login`) and `ensure_authenticated(base_url, api_key) -> str | None`.
- `gigaflow/commands/setup.py` — `_handle_setup` resolves auth via `ensure_authenticated`, passes the credential into `run_wizard`.
- `gigaflow/_setup.py` — `VendorSpec` gains `desc` + `docs_url`; new `_choose_config_source()`; `run_wizard` reworked (new signature, no backend/key prompts, input-method step, project-name copy, no api_key persistence); `_pick_vendor` and Step 3 print descriptions/docs links.
- `docs/gigaflow-env.md` — NEW reference page for the gigaflow.env format.
- `mkdocs.yml`, `docs/index.md`, `README.md` — link the new page; reflect login-based setup.
- `tests/test_setup_wizard_vendors.py` — updated e2e stdin + new unit tests.
- `tests/test_auth_command_flow.py` — new tests for `ensure_authenticated` / `interactive_login`.

---

## Task 1: Move `DEFAULT_BACKEND_URL` into `_config.py`

**Why:** `_setup.run_wizard` needs to detect a non-default backend to print a dev notice. Importing the constant from `cli.py` would create a cycle (`cli` already imports `_setup`). `_config` is imported by both and imports nothing problematic.

**Files:**
- Modify: `gigaflow/_config.py`
- Modify: `gigaflow/cli.py:54`, `gigaflow/cli.py:57-59`
- Test: `tests/test_hosted_backend.py` (existing — must stay green)

- [ ] **Step 1: Add the constant to `_config.py`**

Add after the `CONFIG_PATH` definition (after line 15):

```python
CONFIG_PATH = Path.home() / ".gigaflow" / "config.json"

# Hosted backend — the default so `pip install gigaflow && gigaflow login` works
# out of the box. Local dev overrides via --backend / $GIGAFLOW_BACKEND_URL.
DEFAULT_BACKEND_URL = "https://api.gigaflow.io/api/v1"
```

- [ ] **Step 2: Import it in `cli.py` and delete the local definition**

In `gigaflow/cli.py`, change the import line 24 from:

```python
from gigaflow import _auth, _config
```

to:

```python
from gigaflow import _auth, _config
from gigaflow._config import DEFAULT_BACKEND_URL
```

Then delete the local definition (lines 52-54):

```python
# Hosted backend — the default so `pip install gigaflow && gigaflow login` works
# out of the box. Local dev overrides via --backend / $GIGAFLOW_BACKEND_URL.
DEFAULT_BACKEND_URL = "https://api.gigaflow.io/api/v1"
```

(`_resolve_backend_url` keeps using the now-imported `DEFAULT_BACKEND_URL` unchanged.)

- [ ] **Step 3: Run the backend tests**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_hosted_backend.py tests/test_cli_credential_precedence.py -v`
Expected: PASS (constant relocation is behavior-preserving)

- [ ] **Step 4: Commit**

```bash
git add gigaflow/_config.py gigaflow/cli.py
git commit -m "refactor: move DEFAULT_BACKEND_URL to _config for reuse"
```

---

## Task 2: Add `interactive_login` and `ensure_authenticated` to the auth command

**Why:** `setup` must sign the user in instead of asking for an API key. Extract the reusable email-login flow from `_handle_login`, and add a resolver that prefers any already-available credential before prompting.

**Files:**
- Modify: `gigaflow/commands/auth.py`
- Test: `tests/test_auth_command_flow.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_command_flow.py`:

```python
def test_ensure_authenticated_returns_dev_key_without_login(monkeypatch):
    # An explicit dev key short-circuits — never prompts, never reads credentials.
    called = {}
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda base: called.setdefault("login", True))
    token = auth_cmd.ensure_authenticated("https://b/api/v1", api_key="dev-key")
    assert token == "dev-key"
    assert "login" not in called


def test_ensure_authenticated_uses_existing_token(monkeypatch):
    monkeypatch.setattr(auth_cmd._auth, "access_token", lambda base: "stored-jwt")
    monkeypatch.setattr(auth_cmd, "interactive_login",
                        lambda base: (_ for _ in ()).throw(AssertionError("should not log in")))
    token = auth_cmd.ensure_authenticated("https://b/api/v1", api_key=None)
    assert token == "stored-jwt"


def test_ensure_authenticated_logs_in_when_no_credential(monkeypatch):
    monkeypatch.setattr(auth_cmd._auth, "access_token",
                        iter([None, "fresh-jwt"]).__next__)  # before login: None, after: fresh
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda base: True)
    token = auth_cmd.ensure_authenticated("https://b/api/v1", api_key=None)
    assert token == "fresh-jwt"


def test_ensure_authenticated_returns_none_when_login_fails(monkeypatch):
    monkeypatch.setattr(auth_cmd._auth, "access_token", lambda base: None)
    monkeypatch.setattr(auth_cmd, "interactive_login", lambda base: False)
    assert auth_cmd.ensure_authenticated("https://b/api/v1", api_key=None) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_auth_command_flow.py -v`
Expected: FAIL with `AttributeError: module 'gigaflow.commands.auth' has no attribute 'ensure_authenticated'`

- [ ] **Step 3: Refactor `_handle_login` and add the two helpers**

In `gigaflow/commands/auth.py`, replace `_handle_login` (lines 15-31) with:

```python
def interactive_login(base_url: str) -> bool:
    """Prompt for the waitlist email and sign in. Returns True on success.

    Shared by `gigaflow login` and `gigaflow setup` (auto sign-in)."""
    _fmt.info("GigaFlow is invite-only. Sign in with the email you booked your demo with.")
    _fmt.info(f"No access yet? Book a demo: {_DEFAULT_BOOK_A_DEMO}")
    email = _fmt.prompt("Waitlist email", required=True)
    ok, info = _auth.login(base_url, email)
    if ok:
        _fmt.ok(f"Signed in as {info.get('email', email)}")
        return True
    if info.get("code") == "not_on_allowlist":
        url = info.get("book_a_demo_url", _DEFAULT_BOOK_A_DEMO)
        _fmt.fail("That email isn't on the waitlist yet — you need to book a demo to get access.")
        _fmt.info(f"Book a demo to get in: {url}")
        _fmt.info("Opening the booking page in your browser...")
        webbrowser.open(url)
        return False
    _fmt.fail(f"Login failed: {info.get('error', 'unknown error')}")
    return False


def ensure_authenticated(base_url: str, api_key: str | None = None) -> str | None:
    """Resolve a bearer credential for `setup`, signing in if needed.

    Order: an already-resolved key (dev --api-key/$GIGAFLOW_API_KEY, a prior
    `gigaflow login`, or saved config) → interactive email login. Returns the
    credential string, or None if sign-in failed."""
    if api_key:
        return api_key
    token = _auth.access_token(base_url)
    if token:
        return token
    _fmt.section("Sign in")
    if not interactive_login(base_url):
        return None
    return _auth.access_token(base_url)


def _handle_login(args, base_url: str) -> None:
    _fmt.header("GigaFlow Login")
    interactive_login(base_url)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_auth_command_flow.py -v`
Expected: PASS (both the new tests and the two pre-existing `_handle_login` tests)

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/auth.py tests/test_auth_command_flow.py
git commit -m "feat(auth): add interactive_login + ensure_authenticated for setup"
```

---

## Task 3: Add the input-method step to the wizard

**Why:** Replace the unexplained "Path to gigaflow.env" prompt with an explicit choice between interactive entry and loading a gigaflow.env file, linking the docs.

**Files:**
- Modify: `gigaflow/_setup.py` (add module constant + `_choose_config_source`)
- Test: `tests/test_setup_wizard_vendors.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_wizard_vendors.py` (it already imports `_setup` and defines `_install_prompts`):

```python
def test_choose_config_source_interactive_returns_empty(monkeypatch):
    _install_prompts(monkeypatch, ["1"])  # choose interactive
    assert _setup._choose_config_source() == {}


def test_choose_config_source_blank_defaults_to_interactive(monkeypatch):
    _install_prompts(monkeypatch, [""])  # Enter → default "1"
    assert _setup._choose_config_source() == {}


def test_choose_config_source_loads_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / "gigaflow.env"
    env_file.write_text("GIGAFLOW_PROJECT_NAME=from-file\n")
    _install_prompts(monkeypatch, ["2", str(env_file)])  # choose file, then path
    env = _setup._choose_config_source()
    assert env["GIGAFLOW_PROJECT_NAME"] == "from-file"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_setup_wizard_vendors.py -k choose_config_source -v`
Expected: FAIL with `AttributeError: module 'gigaflow._setup' has no attribute '_choose_config_source'`

- [ ] **Step 3: Implement the constant and function**

In `gigaflow/_setup.py`, add a module constant near the top (after the imports, before `VendorSpec`, around line 9):

```python
GIGAFLOW_ENV_DOCS = "https://docs.gigaflow.io/gigaflow-env/"
```

Then add this function just above `run_wizard` (before line 256):

```python
def _choose_config_source() -> dict:
    """Step 1: let the user enter values interactively or load a gigaflow.env.

    Returns the parsed env dict (empty for interactive entry), used as defaults
    for the prompts that follow."""
    _fmt.section("Step 1: Configuration source")
    print()
    print("  How do you want to provide configuration?")
    print("    1) Enter values interactively (recommended)")
    print("    2) Load from a gigaflow.env file")
    print(f"  See {GIGAFLOW_ENV_DOCS} for the gigaflow.env format.")
    print()
    choice = _fmt.prompt("Choice", "1")
    if choice.strip() == "2":
        env_path = _fmt.prompt("Path to gigaflow.env", required=True)
        env = load_env_file(env_path)
        if env:
            _fmt.ok(f"Loaded env file: {env_path}")
        return env
    return {}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_setup_wizard_vendors.py -k choose_config_source -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gigaflow/_setup.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): add input-method choice step (interactive vs gigaflow.env)"
```

---

## Task 4: Add vendor descriptions + docs URLs to the registry

**Why:** Polish the vendor menu and connection step with one-line descriptions and per-vendor docs links.

**Files:**
- Modify: `gigaflow/_setup.py` (`VendorSpec` dataclass + `VENDORS` list)
- Test: `tests/test_setup_wizard_vendors.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_wizard_vendors.py`:

```python
def test_every_vendor_has_desc_and_docs_url():
    for v in _setup.VENDORS:
        assert v.desc and isinstance(v.desc, str)
        assert v.docs_url.startswith("https://docs.gigaflow.io/sources/")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_setup_wizard_vendors.py -k desc_and_docs -v`
Expected: FAIL with `AttributeError: 'VendorSpec' object has no attribute 'desc'`

- [ ] **Step 3: Add the fields and populate them**

In `gigaflow/_setup.py`, extend the `VendorSpec` dataclass (lines 11-19) — add two fields after `transform_file`:

```python
@dataclass(frozen=True)
class VendorSpec:
    key: str            # backend source_type
    label: str          # menu label
    transform_file: str  # bundled transform filename in gigaflow/transforms/
    desc: str           # one-line menu description
    docs_url: str       # per-vendor setup docs
    # collect(env) -> dict with keys:
    #   connection_url, source_table, api_key (str|None),
    #   vendor_project_name (str|None — used to default the GigaFlow project name)
    collect: Callable[[dict], dict]
```

Then replace the `VENDORS` list (lines 109-115) with:

```python
VENDORS: list[VendorSpec] = [
    VendorSpec("arize_phoenix", "Arize Phoenix   (Postgres)", "arize_phoenix.yml",
               "Postgres database Arize Phoenix writes spans to",
               "https://docs.gigaflow.io/sources/arize-phoenix/", collect_arize_phoenix),
    VendorSpec("braintrust", "Braintrust      (REST API)", "braintrust.yml",
               "Braintrust REST API",
               "https://docs.gigaflow.io/sources/braintrust/", collect_braintrust),
    VendorSpec("logfire", "Logfire         (REST API)", "logfire.yml",
               "Pydantic Logfire REST API",
               "https://docs.gigaflow.io/sources/logfire/", collect_logfire),
    VendorSpec("mlflow", "MLflow          (REST API)", "mlflow.yml",
               "MLflow tracking server REST API",
               "https://docs.gigaflow.io/sources/mlflow/", collect_mlflow),
    VendorSpec("wb_weave", "W&B Weave       (REST API)", "wb_weave.yml",
               "Weights & Biases Weave trace server",
               "https://docs.gigaflow.io/sources/wb-weave/", collect_wb_weave),
]
```

(Field order matters: `collect` is now the last positional arg.)

- [ ] **Step 4: Run the full vendor test file to verify it passes**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_setup_wizard_vendors.py -v`
Expected: PASS (existing registry tests + new `desc_and_docs` test)

- [ ] **Step 5: Commit**

```bash
git add gigaflow/_setup.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): add vendor descriptions and docs URLs to registry"
```

---

## Task 5: Rework `run_wizard` and wire up auth in the setup handler

**Why:** This is the core behavior change — remove the backend-URL and API-key prompts (#2, #3), use the input-method step (#1), explain the project step and stop defaulting to a vendor name (#4), print vendor descriptions/docs (polish), and sign the user in from the handler. Because the `run_wizard` signature changes, the handler and the e2e tests change together.

**Files:**
- Modify: `gigaflow/_setup.py` (`run_wizard`, `_pick_vendor`, Step 3)
- Modify: `gigaflow/commands/setup.py` (`_handle_setup`)
- Test: `tests/test_setup_wizard_vendors.py` (e2e stdin)

- [ ] **Step 1: Update the e2e tests to the new prompt sequence (write the failing tests)**

The new interactive prompt order is: **input-method → vendor → vendor connection → project name → transform**. Backend URL and API key are no longer prompted; auth is satisfied by a dev key set in the environment so the e2e stays focused on the wizard.

In `tests/test_setup_wizard_vendors.py`, replace `test_braintrust_wizard_end_to_end` (lines 216-228) with:

```python
def test_braintrust_wizard_end_to_end(installed_cli, mock_server, clean_env):
    """Braintrust path with the reworked wizard (no backend/api-key prompts)."""
    env = dict(clean_env)
    env["GIGAFLOW_API_KEY"] = "test-key"  # dev key → ensure_authenticated skips login
    # input-method (blank→1), vendor=2, api-base (blank→default),
    # bt-project-name, bt-api-key, gf-project-name (blank→suggested), transform (blank)
    stdin = b"\n2\n\nmy-bt-proj\nbt-secret\n\n\n"
    result = _run(["--backend", mock_server, "setup"], env, stdin=stdin)
    assert result.returncode == 0, result.stderr.decode()
    out_s = result.stdout.decode()
    assert "Datasource registered" in out_s
    assert "Configuration saved" in out_s
    cfg = json.loads((Path(clean_env["HOME"]) / ".gigaflow" / "config.json").read_text())
    assert cfg["project_id"] == MOCK_PROJECT_ID
    assert cfg["datasource_id"] == MOCK_DATASOURCE_ID
```

Replace `test_logfire_wizard_end_to_end` (lines 231-243) with:

```python
def test_logfire_wizard_end_to_end(installed_cli, mock_server, clean_env):
    """Logfire path: no identifier prompt — one fewer prompt than braintrust."""
    env = dict(clean_env)
    env["GIGAFLOW_API_KEY"] = "test-key"
    # input-method (blank→1), vendor=3, api-base (blank→default),
    # read-token, gf-project-name (blank→default), transform (blank)
    stdin = b"\n3\n\nlf-token\n\n\n"
    result = _run(["--backend", mock_server, "setup"], env, stdin=stdin)
    assert result.returncode == 0, result.stderr.decode()
    out_s = result.stdout.decode()
    assert "Datasource registered" in out_s
    assert "Configuration saved" in out_s
    cfg = json.loads((Path(clean_env["HOME"]) / ".gigaflow" / "config.json").read_text())
    assert cfg["project_id"] == MOCK_PROJECT_ID
    assert cfg["datasource_id"] == MOCK_DATASOURCE_ID
```

In `test_wizard_warns_when_nothing_classifies` (lines 246-261), set the dev key and update the stdin to drop the backend/api-key answers. Replace the body's env/stdin setup so it reads:

```python
    os.environ["MOCK_ALL_UNCLASSIFIED"] = "1"
    env = dict(clean_env)
    env["MOCK_ALL_UNCLASSIFIED"] = "1"
    env["GIGAFLOW_API_KEY"] = "test-key"
    try:
        stdin = b"\n2\n\nmy-bt-proj\nbt-secret\n\n\n"
        result = _run(["--backend", mock_server, "setup"], env, stdin=stdin)
```

(Leave the assertions below unchanged.)

- [ ] **Step 2: Run the e2e tests to verify they fail**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_setup_wizard_vendors.py -k end_to_end -v`
Expected: FAIL (current wizard still prompts for backend/api-key, so the scripted stdin desyncs and the run errors / config asserts fail)

- [ ] **Step 3: Rework `_pick_vendor` to show descriptions**

In `gigaflow/_setup.py`, replace `_pick_vendor` (lines 118-129) with:

```python
def _pick_vendor():
    _fmt.section("Step 2: Tracing tool")
    print()
    print("  Which tracing tool are you using?")
    for i, v in enumerate(VENDORS, 1):
        print(f"    {i}) {v.label}")
        print(f"         {v.desc}")
    print()
    choice = _fmt.prompt("Choice", "1")
    vendor = vendor_by_choice(choice)
    if vendor is None:
        _fmt.fail(f"Unknown choice: {choice!r}")
    return vendor
```

- [ ] **Step 4: Rework `run_wizard`**

In `gigaflow/_setup.py`, replace the whole `run_wizard` function (lines 256-344) with:

```python
def run_wizard(base_url: str, api_key: str | None) -> dict | None:
    """Interactive multi-vendor setup wizard. Returns the saved config dict on
    success, None on failure.

    ``base_url`` is the already-resolved backend (--backend / $GIGAFLOW_BACKEND_URL
    / saved config / hosted default). ``api_key`` is the already-resolved bearer
    credential (from `gigaflow login`, a dev key, or saved config); the wizard no
    longer prompts for either."""
    _fmt.header("GigaFlow Setup Wizard")

    # Step 1: how to provide configuration (interactive vs gigaflow.env)
    env = _choose_config_source()

    # Backend is resolved + authenticated already; just verify reachability.
    # Surface a notice when a dev override points away from the hosted default.
    if base_url != _config.DEFAULT_BACKEND_URL:
        _fmt.info(f"Using backend: {base_url}")
    if not check_backend(base_url, api_key):
        return None

    # Step 2: vendor
    vendor = _pick_vendor()
    if vendor is None:
        return None

    # Step 3: connection (vendor-specific)
    _fmt.section("Step 3: Connection")
    _fmt.info(f"Where to find these credentials: {vendor.docs_url}")
    conn = vendor.collect(env)

    # Step 4: project
    _fmt.section("Step 4: Project")
    print()
    print("  A project is a namespace that groups your traces and evals in GigaFlow.")
    print("  Use one project per app or environment (e.g. 'checkout-bot', 'prod').")
    print()
    suggested = conn.get("vendor_project_name") or env.get("GIGAFLOW_PROJECT_NAME") or "default"
    project_name = _fmt.prompt("GigaFlow project name", suggested)
    project_id = create_project(base_url, project_name, api_key)
    if not project_id:
        return None

    # Step 5: transform (vendor built-in by default)
    _fmt.section("Step 5: Transform")
    label = vendor.label.split("(")[0].strip()
    transform_path = _fmt.prompt(
        f"Path to transform.yml (leave blank for built-in {label} config)",
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
    _config.save(config)
    _fmt.ok(f"Configuration saved to {_config.CONFIG_PATH}")
    return config
```

Key changes vs. the old body: removed the gigaflow.env-path prompt and the "Step 1: backend + key" block (backend-URL + API-key prompts); the credential is the `api_key` parameter; project-name fallback is `"default"` (not `f"{vendor.key}-project"`); the wizard no longer persists `api_key` into config (the JWT lives in `credentials.json`; dev keys come from env/flag each run).

- [ ] **Step 5: Wire `ensure_authenticated` into `_handle_setup`**

In `gigaflow/commands/setup.py`, update the imports (lines 5-6) to:

```python
from gigaflow import _config, _fmt
from gigaflow._setup import do_sync, run_wizard
from gigaflow.commands.auth import ensure_authenticated
```

Then replace `_handle_setup` (lines 14-30) with:

```python
def _handle_setup(args, base_url: str) -> None:
    config = _config.load()
    if config.get("datasource_id"):
        print(f"  Already configured (project: {config.get('project_id', '?')[:8]}…)")
        print("  To reconfigure, run:  gigaflow config clear  then  gigaflow setup")
        print()
        return
    api_key = ensure_authenticated(base_url, getattr(args, "api_key", None))
    if not api_key:
        _fmt.fail("Sign-in required to run setup. Run:  gigaflow login")
        sys.exit(1)
    result = run_wizard(base_url, api_key)
    if result is None:
        sys.exit(1)
    _fmt.section("Next steps")
    print()
    print("  gigaflow traces")
    print("  gigaflow spans <trace_id>")
    print("  gigaflow sync")
    print(f"  {base_url.replace('/api/v1', '')}/api/v1/docs")
    print()
```

- [ ] **Step 6: Run the e2e tests to verify they pass**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest tests/test_setup_wizard_vendors.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add gigaflow/_setup.py gigaflow/commands/setup.py tests/test_setup_wizard_vendors.py
git commit -m "feat(setup): drop backend/api-key prompts, sign in via login, explain project step"
```

---

## Task 6: Add the gigaflow.env docs page and update navigation

**Why:** The setup prompt now links `https://docs.gigaflow.io/gigaflow-env/`. That page must exist and document every recognized field. Also reflect login-based setup (no API key) in the index and README.

**Files:**
- Create: `docs/gigaflow-env.md`
- Modify: `mkdocs.yml` (nav)
- Modify: `docs/index.md`, `README.md`

- [ ] **Step 1: Create `docs/gigaflow-env.md`**

```markdown
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
```

- [ ] **Step 2: Add the page to `mkdocs.yml` nav**

In `mkdocs.yml`, add a nav entry under `Home` (after the `- Home: index.md` line):

```yaml
nav:
  - Home: index.md
  - The gigaflow.env file: gigaflow-env.md
  - Connect a source:
```

- [ ] **Step 3: Update `docs/index.md` and `README.md` for login-based setup**

Read both files first:

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && sed -n '1,60p' docs/index.md && echo '=== README ===' && sed -n '20,75p' README.md`

Then edit so the configure/quickstart sections say: run `gigaflow setup`, which signs you in with your waitlist email (no API key needed) and walks you through choosing your tracing tool and project. Remove or relabel any text that tells users to set `GIGAFLOW_API_KEY` / a backend URL as a required step — present those only as developer overrides, and link `gigaflow-env.md`. Keep edits minimal and consistent with each file's existing voice; do not invent commands beyond `gigaflow login` / `gigaflow setup`.

- [ ] **Step 4: Verify docs build (mkdocs strict, snippets/link check)**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run mkdocs build --strict 2>&1 | tail -20`
Expected: build succeeds with no warnings (exit 0). If `mkdocs` isn't in the env, run `uv run --with mkdocs-material mkdocs build --strict`.

- [ ] **Step 5: Commit**

```bash
git add docs/gigaflow-env.md mkdocs.yml docs/index.md README.md
git commit -m "docs: add gigaflow.env reference; reflect login-based setup"
```

---

## Task 7: Full suite + manual smoke check

**Why:** Confirm nothing else regressed and the new flow reads well.

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run pytest -q`
Expected: all tests pass. (If `installed_cli`-based tests need pip in the uv venv, seed it first: `uv run python -m ensurepip` — see the SDK venv note.)

- [ ] **Step 2: Lint (match the repo's tooling)**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && uv run ruff check gigaflow tests 2>&1 | tail -20`
Expected: no errors (skip if ruff isn't configured for this repo).

- [ ] **Step 3: Manual smoke of the wizard copy (dev backend, dev key, abort early)**

Run: `cd /Users/jamesgao/Projects/gigaflow-ai-incorporated/gigaflow-sdk/.claude/worktrees/setup-friction-fixes && GIGAFLOW_API_KEY=x printf '1\n' | uv run gigaflow --backend http://localhost:9/api/v1 setup 2>&1 | head -30`
Expected: shows "Step 1: Configuration source" with the interactive/file choice and the docs link, prints `Using backend: http://localhost:9/api/v1`, then fails the backend reachability check (expected — no server). Confirms no backend-URL or API-key prompt appears and the dev key suppressed the login prompt.

- [ ] **Step 4: Commit (only if Steps 1-2 required fixes)**

```bash
git add -A
git commit -m "fix: address test/lint findings for setup friction fixes"
```

---

## Self-Review

**Spec coverage:**
- #1 gigaflow.env friction → Task 3 (input-method step + docs link) + Task 6 (docs page).
- #2 backend URL default, no prompt → Task 5 (prompt removed; dev notice) + Task 1 (shared constant).
- #3 login instead of API key → Task 2 (`ensure_authenticated`/`interactive_login`) + Task 5 (handler wiring, prompt removed); `login`/`logout`/`whoami` kept (Task 2 only refactors `_handle_login`).
- #4 project name: explain + suggest, no vendor default → Task 5 (copy + `"default"` fallback, vendor suggestion preserved via `vendor_project_name`).
- Vendor flow polish → Task 4 (registry desc/docs) + Task 5 (`_pick_vendor` + Step 3 docs link).
- Supporting: docs page + README/index/nav → Task 6; `ensure_authenticated` helper → Task 2; tests → Tasks 2-5, 7.

**Placeholder scan:** none — every code step shows complete code; the one prose-edit step (Task 6 Step 3) is bounded by a read command and explicit constraints because it touches free-form marketing copy.

**Type/name consistency:** `ensure_authenticated(base_url, api_key)` and `interactive_login(base_url)` defined in Task 2 and called identically in Task 5; `run_wizard(base_url, api_key)` defined in Task 5 Step 4 and called in Task 5 Step 5; `_choose_config_source()` defined in Task 3 and called in Task 5; `DEFAULT_BACKEND_URL` defined in Task 1 and referenced via `_config.DEFAULT_BACKEND_URL` in Task 5; `VendorSpec.desc`/`.docs_url` defined in Task 4 and used in Task 5.
