import gigaflow.commands.compute as C


def _metrics_row(run_id="r1", g=0.5, tc=0.1, cost="0.05"):
    return {"columns": ["run_id", "groundedness", "tool_consumption", "total_cost_usd"],
            "rows": [[run_id, g, tc, cost]]}


def test_poll_for_run_returns_metrics_when_run_appears(monkeypatch):
    calls = {"n": 0}

    def fake_api(base, method, path, body=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return 200, {"columns": ["run_id"], "rows": []}  # not ready
        return 200, _metrics_row()
    monkeypatch.setattr(C, "api", fake_api)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    g, tc, usage = C._poll_for_run("http://b", "t1", None, deadline_s=30, interval_s=1)
    assert g == 0.5 and tc == 0.1
    assert calls["n"] >= 3


def test_poll_for_run_times_out(monkeypatch):
    def fake_api(*a, **k):
        return 200, {"columns": ["run_id"], "rows": []}
    monkeypatch.setattr(C, "api", fake_api)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    # fake monotonic so the deadline is hit deterministically
    t = {"v": 0.0}
    monkeypatch.setattr(C.time, "monotonic", lambda: t.__setitem__("v", t["v"] + 5) or t["v"])
    import pytest
    with pytest.raises(C.ComputeStillRunning):
        C._poll_for_run("http://b", "t1", None, deadline_s=10, interval_s=1)


def test_run_one_polls_on_timeout_single_post(monkeypatch):
    posts = {"n": 0}

    def fake_api(base, method, path, body=None, **kw):
        if path.startswith("/flow/"):
            posts["n"] += 1
            return None, {"error": "request timed out"}   # client timeout
        return 200, _metrics_row()                          # poll query
    monkeypatch.setattr(C, "api", fake_api)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    g, tc, usage = C._run_one("http://b", "t1", {"api_key": "sk"}, None)
    assert g == 0.5
    assert posts["n"] == 1   # exactly ONE compute POST — no duplicate run


def test_run_one_polls_on_504(monkeypatch):
    def fake_api(base, method, path, body=None, **kw):
        if path.startswith("/flow/"):
            return 504, {"error": "<html>504</html>"}
        return 200, _metrics_row()
    monkeypatch.setattr(C, "api", fake_api)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    g, tc, usage = C._run_one("http://b", "t1", {"api_key": "sk"}, None)
    assert g == 0.5


def test_run_one_real_connection_error_still_raises(monkeypatch):
    def fake_api(base, method, path, body=None, **kw):
        return None, {"error": "Connection refused"}
    monkeypatch.setattr(C, "api", fake_api)
    import pytest
    with pytest.raises(RuntimeError) as e:
        C._run_one("http://b", "t1", {"api_key": "sk"}, None)
    assert "reach" in str(e.value).lower()


def test_compute_argparser_has_timeout():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers()
    C.register(sub)
    ns = p.parse_args(["compute", "SELECT 1", "--timeout", "42"])
    assert ns.timeout == 42.0
