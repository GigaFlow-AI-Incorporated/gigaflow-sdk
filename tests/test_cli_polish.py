import contextlib
import importlib.metadata
import io

import pytest

import gigaflow.cli as cli


def test_version_flag_prints_version():
    out = io.StringIO()
    with pytest.raises(SystemExit), contextlib.redirect_stdout(out):
        cli.main(["--version"])
    assert importlib.metadata.version("gigaflow") in out.getvalue()


def test_traces_hint_points_at_compute():
    import inspect as _inspect

    import gigaflow.commands.traces as T
    src = _inspect.getsource(T)
    assert "gigaflow run flow" not in src
    assert "gigaflow compute" in src
