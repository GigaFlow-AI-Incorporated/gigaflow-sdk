import gigaflow.commands._retry as R


def test_get_with_retry_recovers_from_404(monkeypatch):
    seq = [(404, {"detail": "Trace not found"}), (404, {"detail": "Trace not found"}), (200, {"ok": True})]
    calls = {"n": 0}

    def fake_api(base, method, path, **kw):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]
    monkeypatch.setattr(R, "api", fake_api)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    status, resp = R.get_with_retry("http://b", "/traces/x", None, tries=5, delay=0.01)
    assert status == 200 and resp == {"ok": True}
    assert calls["n"] == 3


def test_get_with_retry_gives_up_after_tries(monkeypatch):
    def fake_api(*a, **k):
        return 404, {"detail": "Trace not found"}
    monkeypatch.setattr(R, "api", fake_api)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    status, resp = R.get_with_retry("http://b", "/traces/x", None, tries=3, delay=0.01)
    assert status == 404


def test_get_with_retry_non_404_returns_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_api(*a, **k):
        calls["n"] += 1
        return 500, {"detail": "boom"}
    monkeypatch.setattr(R, "api", fake_api)
    status, resp = R.get_with_retry("http://b", "/traces/x", None, tries=5, delay=0.01)
    assert status == 500 and calls["n"] == 1
