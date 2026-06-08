"""Unit tests for the vendor registry and per-vendor wizard branches."""
import importlib.resources

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
