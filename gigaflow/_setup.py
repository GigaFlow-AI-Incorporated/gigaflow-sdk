"""Interactive setup wizard: project creation, transform upload, datasource registration, sync."""

import importlib.resources
from collections.abc import Callable
from dataclasses import dataclass

from gigaflow import _config, _fmt
from gigaflow._http import api

GIGAFLOW_ENV_DOCS = "https://docs.gigaflow.io/gigaflow-env/"


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


def vendor_by_choice(choice: str) -> VendorSpec | None:
    """Map a 1-indexed menu string to a VendorSpec. Blank → Arize Phoenix."""
    choice = (choice or "").strip()
    if choice == "":
        return VENDORS[0]
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(VENDORS):
            return VENDORS[idx]
    return None


# ── Per-vendor connection collectors ─────────────────────────────────────────

def collect_arize_phoenix(env: dict) -> dict:
    _fmt.section("Connection: Arize Phoenix database")
    print()
    print("  Enter the PostgreSQL connection Arize Phoenix writes to.")
    print("  Tip: if GigaFlow runs in Docker, use 'host.docker.internal'.")
    print()
    host = _fmt.prompt("Host", env.get("GIGAFLOW_DB_HOST", "host.docker.internal"))
    port = _fmt.prompt("Port", env.get("GIGAFLOW_DB_PORT", ""), required=True)
    user = _fmt.prompt("User", env.get("GIGAFLOW_DB_USER", "postgres"))
    if env.get("GIGAFLOW_DB_PASSWORD"):
        password = env["GIGAFLOW_DB_PASSWORD"]
        _fmt.info("Password: [from env file]")
    else:
        password = _fmt.prompt_password("Password")
    db = _fmt.prompt("Database", env.get("GIGAFLOW_DB_NAME", "postgres"))
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
    url = _fmt.prompt("API base URL", env.get(url_env, default_url), required=True).rstrip("/")
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


def _load_transform(filename: str) -> str:
    ref = importlib.resources.files("gigaflow.transforms").joinpath(filename)
    return ref.read_text(encoding="utf-8")


def _load_default_transform() -> str:
    """Load the built-in Arize Phoenix transform config from the package."""
    return _load_transform("arize_phoenix.yml")


def load_env_file(path: str) -> dict:
    """Parse a .env-style file and return key-value pairs.

    Supports comments (#), blank lines, and optionally quoted values.
    """
    env: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key:
                    env[key] = value
    except OSError as e:
        _fmt.fail(f"Could not read env file: {e}")
    return env

ARIZE_TRANSFORM_YAML = _load_default_transform()


def _resolve_key(api_key: str | None) -> str | None:
    """Fall back to the saved config key when a caller doesn't pass one.

    Lets the plain ``do_sync(base_url, ds_id)`` call sites in setup/traces pick
    up a configured key without every caller having to thread it through.
    """
    return api_key if api_key is not None else _config.get("api_key")


def check_backend(base_url: str, api_key: str | None = None) -> bool:
    status, resp = api(base_url, "GET", "/health", api_key=_resolve_key(api_key))
    if status is None:
        _fmt.fail(f"Could not reach gigaflow backend at {base_url}")
        _fmt.info("Check the URL ($GIGAFLOW_BACKEND_URL / --backend) and that the backend is running.")
        return False
    if status in (401, 403):
        _fmt.fail("Authentication failed — run `gigaflow login` to sign in (or set --api-key / $GIGAFLOW_API_KEY for local dev).")
        return False
    if status != 200:
        _fmt.fail(f"Backend returned {status}: {resp}")
        return False
    _fmt.ok(f"Backend reachable at {base_url}")
    return True


def create_project(base_url: str, name: str, api_key: str | None = None) -> str | None:
    status, resp = api(base_url, "POST", "/projects/", {"name": name}, api_key=_resolve_key(api_key))
    if status != 200:
        _fmt.fail(f"Failed to create project ({status}): {resp}")
        return None
    project_id = resp["project_id"]
    _fmt.ok(f"Project created: {name}")
    _fmt.info(f"project_id: {project_id}")
    return project_id


def upload_transform(base_url: str, project_id: str, yaml_content: str = ARIZE_TRANSFORM_YAML, api_key: str | None = None) -> bool:
    status, resp = api(
        base_url, "PUT", f"/projects/{project_id}/transform",
        yaml_content, content_type="text/plain", api_key=_resolve_key(api_key),
    )
    if status != 200:
        _fmt.fail(f"Failed to upload transform config ({status}): {resp}")
        return False
    primitives = list(resp.get("transform_config", {}).get("primitives", {}).keys())
    _fmt.ok("Transform config uploaded")
    _fmt.info(f"primitives: {', '.join(primitives)}")
    return True


def register_datasource(base_url: str, project_id: str, connection_url: str, source_table: str,
                        api_key: str | None = None, source_type: str = "arize_phoenix", name: str | None = None) -> str | None:
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


def do_sync(base_url: str, datasource_id: str, api_key: str | None = None) -> tuple[int, int] | None:
    status, resp = api(base_url, "POST", f"/datasources/{datasource_id}/sync", api_key=_resolve_key(api_key))
    if status != 200:
        _fmt.fail(f"Sync failed ({status}): {resp.get('detail', resp)}")
        detail = str(resp.get("detail", ""))
        if "connect" in detail.lower() or status == 502:
            _fmt.info("Could not connect to the source database.")
            _fmt.info("If Arize is running in Docker, try 'host.docker.internal' as the host.")
        return None
    synced_traces = resp.get("synced_traces", 0)
    synced_spans = resp.get("synced_spans", 0)
    _fmt.ok(f"Sync complete: {synced_traces} trace(s), {synced_spans} span(s)")
    return synced_traces, synced_spans


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


_PRIMITIVES = ("llm_call", "tool_invocation", "user_input", "transform")


def _classification_summary(spans: list) -> tuple[dict, int]:
    counts = dict.fromkeys(_PRIMITIVES, 0)
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
        return True
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
