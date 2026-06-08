"""Unit tests for the vendor registry and per-vendor wizard branches."""
from gigaflow import _setup


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


import importlib.resources


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


def test_mlflow_transform_classifies_on_spantype():
    text = _read_transform("mlflow.yml")
    assert "mlflow" in text
    assert "attributes.mlflow.spanType" in text
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text


def test_wb_weave_transform_is_template_with_span_name_filter():
    text = _read_transform("wb_weave.yml")
    assert "wb_weave" in text
    assert "span_name" in text
    assert "TEMPLATE" in text
    for prim in ("llm_call", "tool_invocation", "user_input"):
        assert prim in text
