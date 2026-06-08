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
