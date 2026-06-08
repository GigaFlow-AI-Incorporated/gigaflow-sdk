"""Unit tests for the vendor registry and per-vendor wizard branches."""
import importlib.resources
import json
import os
from pathlib import Path

from _constants import MOCK_DATASOURCE_ID, MOCK_PROJECT_ID  # noqa: E402
from test_commands import run as _run  # noqa: E402

from gigaflow import _setup
from gigaflow import _setup as setup_mod


def test_vendor_registry_has_all_five():
    keys = [v.key for v in _setup.VENDORS]
    assert keys == ["arize_phoenix", "braintrust", "logfire", "mlflow", "wb_weave"]


def test_vendor_lookup_by_choice_number():
    assert _setup.vendor_by_choice("1").key == "arize_phoenix"
    assert _setup.vendor_by_choice("2").key == "braintrust"
    assert _setup.vendor_by_choice("5").key == "wb_weave"


def test_vendor_lookup_blank_defaults_to_arize():
    assert _setup.vendor_by_choice("").key == "arize_phoenix"


def test_vendor_lookup_invalid_returns_none():
    assert _setup.vendor_by_choice("9") is None
    assert _setup.vendor_by_choice("banana") is None


def test_each_vendor_declares_a_transform_name():
    for v in _setup.VENDORS:
        assert v.transform_file.endswith(".yml")


def _read_transform(name: str) -> str:
    return importlib.resources.files("gigaflow.transforms").joinpath(name).read_text()


def test_all_registry_transforms_exist_as_package_data():
    # The registry must never reference a transform file that isn't shipped.
    for v in _setup.VENDORS:
        ref = importlib.resources.files("gigaflow.transforms").joinpath(v.transform_file)
        assert ref.is_file(), f"missing bundled transform: {v.transform_file}"


def test_braintrust_transform_classifies_on_span_type():
    text = _read_transform("braintrust.yml")
    assert "source:" in text and "braintrust" in text
    assert "span_attributes.type" in text
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text
    assert "completion:" in text          # llm output mapped
    assert "tool_output:" in text         # tool output mapped
    assert "content:" in text             # user_input mapped


def test_mlflow_transform_classifies_on_spantype():
    text = _read_transform("mlflow.yml")
    assert "mlflow" in text
    assert "attributes.mlflow.spanType" in text
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text
    assert "completion:" in text
    assert "tool_output:" in text
    assert "content:" in text


def test_wb_weave_transform_is_template_with_span_name_filter():
    text = _read_transform("wb_weave.yml")
    assert "wb_weave" in text
    assert "span_name" in text
    assert "TEMPLATE" in text
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text
    assert "completion:" in text
    assert "tool_output:" in text
    assert "content:" in text


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


def test_register_datasource_arize_omits_api_key(monkeypatch):
    captured = {}

    def fake_api(base_url, method, path, body=None, **kw):
        captured["body"] = body
        return 200, {"datasource_id": "ds-2"}

    monkeypatch.setattr(setup_mod, "api", fake_api)
    setup_mod.register_datasource(
        "http://x/api/v1", "proj-1",
        connection_url="postgresql://u:p@h:5432/db",
        source_table="spans",
        api_key=None,
        source_type="arize_phoenix",
    )
    assert captured["body"]["source_type"] == "arize_phoenix"
    assert "api_key" not in captured["body"]   # None → omitted
    assert captured["body"]["name"] == "arize_phoenix"  # defaults to source_type


class _Prompts:
    """Feed scripted answers to _fmt.prompt / prompt_password in order.

    Mirrors the real _fmt.prompt fallback: an empty answer uses the default,
    matching what happens when the user presses Enter at a prompt with a default.
    """
    def __init__(self, answers):
        self.answers = list(answers)
    def prompt(self, label, default="", required=False):
        val = self.answers.pop(0) if self.answers else ""
        return val if val else default
    def prompt_password(self, label):
        return self.answers.pop(0) if self.answers else ""


def _install_prompts(monkeypatch, answers):
    p = _Prompts(answers)
    monkeypatch.setattr(_setup._fmt, "prompt", p.prompt)
    monkeypatch.setattr(_setup._fmt, "prompt_password", p.prompt_password)


def test_collect_braintrust(monkeypatch):
    # answers: api base (blank → default), project name, api key
    _install_prompts(monkeypatch, ["", "my-bt-proj", "bt-secret"])
    out = _setup.collect_braintrust({})
    assert out["connection_url"] == "https://api.braintrust.dev"
    assert out["source_table"] == "my-bt-proj"
    assert out["api_key"] == "bt-secret"
    assert out["vendor_project_name"] == "my-bt-proj"


def test_collect_wb_weave(monkeypatch):
    _install_prompts(monkeypatch, ["", "my-org/rag-eval", "wandb-key"])
    out = _setup.collect_wb_weave({})
    assert out["connection_url"] == "https://trace.wandb.ai"
    assert out["source_table"] == "my-org/rag-eval"
    assert out["api_key"] == "wandb-key"
    assert out["vendor_project_name"] == "my-org/rag-eval"


def test_collect_logfire_has_no_vendor_project(monkeypatch):
    _install_prompts(monkeypatch, ["", "logfire-read-token"])
    out = _setup.collect_logfire({})
    assert out["connection_url"] == "https://logfire-us.pydantic.dev"
    assert out["api_key"] == "logfire-read-token"
    assert out["vendor_project_name"] is None


def test_collect_arize_builds_postgres_url(monkeypatch):
    # host, port, user, password, db, table
    _install_prompts(monkeypatch, ["host.docker.internal", "5432", "postgres", "pw", "postgres", "spans"])
    out = _setup.collect_arize_phoenix({})
    assert out["connection_url"] == "postgresql://postgres:pw@host.docker.internal:5432/postgres"
    assert out["source_table"] == "spans"
    assert out["api_key"] is None
    assert out["vendor_project_name"] is None


def test_collectors_are_bound_into_registry():
    for v in _setup.VENDORS:
        assert callable(v.collect)


def test_classification_summary_counts_primitives():
    spans = [
        {"primitive_type": "llm_call"},
        {"primitive_type": "llm_call"},
        {"primitive_type": "tool_invocation"},
        {"primitive_type": None},
        {},  # no primitive_type
    ]
    counts, unclassified = _setup._classification_summary(spans)
    assert counts["llm_call"] == 2
    assert counts["tool_invocation"] == 1
    assert unclassified == 2


def test_classification_summary_all_unclassified():
    spans = [{"primitive_type": None}, {}]
    counts, unclassified = _setup._classification_summary(spans)
    assert sum(counts.values()) == 0
    assert unclassified == 2


# ── per-vendor e2e tests (subprocess against mock server) ────────────────────


def test_braintrust_wizard_end_to_end(installed_cli, mock_server, clean_env):
    """Braintrust path: vendor=2, blank API base, project name, API key, blank GF project, blank transform."""
    # env-file, backend, gf-api-key, vendor=2, api-base (blank→default),
    # bt-project-name, bt-api-key, gf-project-name (blank→suggested), transform (blank)
    stdin = b"\n\n\n2\n\nmy-bt-proj\nbt-secret\n\n\n"
    result = _run(["--backend", mock_server, "setup"], clean_env, stdin=stdin)
    assert result.returncode == 0, result.stderr.decode()
    out_s = result.stdout.decode()
    assert "Datasource registered" in out_s
    assert "Configuration saved" in out_s
    cfg = json.loads((Path(clean_env["HOME"]) / ".gigaflow" / "config.json").read_text())
    assert cfg["project_id"] == MOCK_PROJECT_ID
    assert cfg["datasource_id"] == MOCK_DATASOURCE_ID


def test_logfire_wizard_end_to_end(installed_cli, mock_server, clean_env):
    """Logfire path: no identifier prompt — one fewer prompt than braintrust."""
    # env-file, backend, gf-api-key, vendor=3, api-base (blank→default),
    # read-token, gf-project-name (blank→logfire-project), transform (blank)
    stdin = b"\n\n\n3\n\nlf-token\n\n\n"
    result = _run(["--backend", mock_server, "setup"], clean_env, stdin=stdin)
    assert result.returncode == 0, result.stderr.decode()
    out_s = result.stdout.decode()
    assert "Datasource registered" in out_s
    assert "Configuration saved" in out_s
    cfg = json.loads((Path(clean_env["HOME"]) / ".gigaflow" / "config.json").read_text())
    assert cfg["project_id"] == MOCK_PROJECT_ID
    assert cfg["datasource_id"] == MOCK_DATASOURCE_ID


def test_wizard_warns_when_nothing_classifies(installed_cli, mock_server, clean_env):
    """When all spans are unclassified the wizard prints a warning with config-clear hint."""
    # Set MOCK_ALL_UNCLASSIFIED in the test process so the in-process mock server sees it.
    os.environ["MOCK_ALL_UNCLASSIFIED"] = "1"
    env = dict(clean_env)
    env["MOCK_ALL_UNCLASSIFIED"] = "1"
    try:
        stdin = b"\n\n\n2\n\nmy-bt-proj\nbt-secret\n\n\n"
        result = _run(["--backend", mock_server, "setup"], env, stdin=stdin)
        assert result.returncode == 0, result.stderr.decode()
        out_s = result.stdout.decode()
        err_s = result.stderr.decode()
        assert "None of your spans matched" in out_s or "None of your spans matched" in err_s
        assert "config clear" in out_s
    finally:
        os.environ.pop("MOCK_ALL_UNCLASSIFIED", None)


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


def test_every_vendor_has_desc_and_docs_url():
    for v in _setup.VENDORS:
        assert v.desc and isinstance(v.desc, str)
        assert v.docs_url.startswith("https://docs.gigaflow.io/sources/")
