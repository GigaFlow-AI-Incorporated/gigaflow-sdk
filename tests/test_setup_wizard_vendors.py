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
