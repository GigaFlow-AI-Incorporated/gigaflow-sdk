"""The 2xx success predicate shared by login / query / compute."""
import pytest

from gigaflow._http import ok


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_ok_accepts_2xx(status):
    assert ok(status) is True


@pytest.mark.parametrize("status", [None, 199, 300, 301, 400, 401, 404, 422, 500])
def test_ok_rejects_non_2xx(status):
    assert ok(status) is False
