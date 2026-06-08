# Onboarding Robustness & Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the documented Braintrust new-user path (`gigaflow setup` → `compute` → `inspect`) complete on the hosted backend with no false-failure command and no duplicate runs.

**Architecture:** Additive changes to the zero-dependency CLI, stacked on PR #9. The keystone is poll-after-timeout in `compute`: the hosted gateway 504s a long synchronous `POST /flow/{id}` but the backend finishes asynchronously, so on timeout/504 we poll `trace_metrics` for the run instead of erroring (which also removes the duplicate-run footgun). Plus a 404-retry wrapper for read-after-write lag, and small UX fixes.

**Tech Stack:** Python 3 stdlib only (`urllib`, `argparse`, `importlib.metadata`); pytest with `api()` mocked (no `installed_cli` subprocess fixture, so tests run under plain `uv run pytest`).

---

## Conventions

- Run tests from the worktree root: `uv run pytest tests/<file> -v`. If uv's venv lacks pip, seed once: `uv run python -m ensurepip` (these unit tests mock `api()` and do NOT use the `installed_cli` fixture, so pip is not strictly needed).
- All file paths are relative to the `gigaflow-sdk` worktree root `.claude/worktrees/onboarding-robustness/`.
- Commit after each task.

## File Structure

- `gigaflow/_http.py` — add `COMPUTE_TIMEOUT`; expose a timeout knob (already a param). No contract change.
- `gigaflow/commands/compute.py` — poll-after-timeout in `_run_one`; `--timeout`; optional `OPENAI_API_KEY`; new helpers `_poll_for_run`, `_is_pending`.
- `gigaflow/commands/_retry.py` (Create) — shared `get_with_retry()` (404 backoff).
- `gigaflow/commands/inspect.py` — use `get_with_retry` for by-id trace + spans.
- `gigaflow/commands/traces.py` — use `get_with_retry` for spans; fix the `run flow` hint.
- `gigaflow/cli.py` — add `--version`; vendor-neutral description.
- `tests/test_compute_robustness.py` (Create) — poll/dedup/deadline/openai-optional.
- `tests/test_readafterwrite_retry.py` (Create) — 404-then-200 retry.
- `tests/test_cli_polish.py` (Create) — `--version`, hint string.

---

### Task 1: Poll-after-timeout helpers in compute

**Files:**
- Modify: `gigaflow/commands/compute.py`
- Test: `tests/test_compute_robustness.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_compute_robustness.py
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
    def fake_api(*a, **k): return 200, {"columns": ["run_id"], "rows": []}
    monkeypatch.setattr(C, "api", fake_api)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    # fake monotonic so the deadline is hit deterministically
    t = {"v": 0.0}
    monkeypatch.setattr(C.time, "monotonic", lambda: t.__setitem__("v", t["v"] + 5) or t["v"])
    import pytest
    with pytest.raises(C.ComputeStillRunning):
        C._poll_for_run("http://b", "t1", None, deadline_s=10, interval_s=1)
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_compute_robustness.py -v`
Expected: FAIL (`_poll_for_run` / `ComputeStillRunning` not defined).

- [ ] **Step 3: Implement**

Add near the top of `compute.py` (it already imports `time`? if not, `import time`):

```python
class ComputeStillRunning(RuntimeError):
    """Raised when Flow is still computing server-side past the poll deadline."""


def _poll_for_run(base_url, trace_id, gigaflow_key, deadline_s=300, interval_s=5):
    """Poll trace_metrics until this trace has a run_id, or raise ComputeStillRunning."""
    sql = (
        "SELECT run_id, groundedness, tool_consumption, total_cost_usd "
        f"FROM trace_metrics WHERE trace_id = '{trace_id}' AND run_id IS NOT NULL"
    )
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        status, result = api(base_url, "POST", "/query/", {"sql": sql, "limit": 1},
                             api_key=gigaflow_key)
        if status == 200:
            cols = result.get("columns", [])
            rows = result.get("rows", [])
            if rows and "run_id" in cols:
                row = rows[0]

                def col(name):
                    return row[cols.index(name)] if name in cols else None
                return (col("groundedness") or 0.0, col("tool_consumption") or 0.0,
                        {"total_cost_usd": col("total_cost_usd")})
        time.sleep(interval_s)
    raise ComputeStillRunning(
        f"Flow for {trace_id[:8]}… is still computing on the server after "
        f"{deadline_s}s. Re-run `gigaflow compute` later to pick up the result."
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_compute_robustness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/compute.py tests/test_compute_robustness.py
git commit -m "feat(compute): add _poll_for_run for async server-side completion"
```

---

### Task 2: Wire poll into `_run_one` (504/timeout → poll, not fail)

**Files:**
- Modify: `gigaflow/commands/compute.py` (`_run_one`)
- Test: `tests/test_compute_robustness.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_compute_robustness.py -k run_one -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — replace the failure branch in `_run_one`:

```python
def _run_one(base_url, trace_id, body, gigaflow_key=None):
    status, resp = api(base_url, "POST", f"/flow/{trace_id}", body,
                       api_key=gigaflow_key, timeout=COMPUTE_TIMEOUT)
    if status != 200:
        if status in (502, 503, 504):
            # Gateway timed out a long synchronous compute; the backend keeps
            # going. Poll for the run instead of failing / re-POSTing.
            return _poll_for_run(base_url, trace_id, gigaflow_key)
        if status is None:
            reason = (resp or {}).get("error", "") if isinstance(resp, dict) else ""
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                return _poll_for_run(base_url, trace_id, gigaflow_key)
            raise RuntimeError(unreachable_hint(base_url))
        if status in (401, 403):
            raise RuntimeError(auth_error_hint())
        detail = resp.get("detail", str(resp)) if isinstance(resp, dict) else str(resp)
        raise RuntimeError(detail)
    metrics = resp.get("metrics", {}) if isinstance(resp, dict) else {}
    token_usage = resp.get("token_usage") if isinstance(resp, dict) else None
    return (metrics.get("groundedness") or 0.0,
            metrics.get("tool_consumption") or 0.0,
            token_usage or {})
```

Add `COMPUTE_TIMEOUT` constant near the top of `compute.py`:

```python
import os
COMPUTE_TIMEOUT = float(os.environ.get("GIGAFLOW_COMPUTE_TIMEOUT", "180"))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_compute_robustness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/compute.py tests/test_compute_robustness.py
git commit -m "feat(compute): poll on 504/timeout instead of false failure; no dup runs"
```

---

### Task 3: `--timeout` flag + ComputeStillRunning handled in the loop

**Files:**
- Modify: `gigaflow/commands/compute.py` (`register`, `_handle_compute` loop)
- Test: `tests/test_compute_robustness.py`

- [ ] **Step 1: Write failing test**

```python
def test_compute_argparser_has_timeout():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers()
    C.register(sub)
    ns = p.parse_args(["compute", "SELECT 1", "--timeout", "42"])
    assert ns.timeout == 42.0
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_compute_robustness.py -k timeout -v`
Expected: FAIL (unrecognized `--timeout`).

- [ ] **Step 3: Implement**

In `register(...)` add:

```python
    p.add_argument("--timeout", type=float, default=None,
                   help="Per-trace compute timeout in seconds (default: 180 / "
                        "$GIGAFLOW_COMPUTE_TIMEOUT)")
```

In `_handle_compute`, after parsing, set the module timeout if provided:

```python
    global COMPUTE_TIMEOUT
    if getattr(args, "timeout", None):
        COMPUTE_TIMEOUT = args.timeout
```

In the `as_completed` loop, treat `ComputeStillRunning` as a soft note (not a hard failure that exits 1):

```python
            except ComputeStillRunning as exc:
                _fmt.warn(f"[{i:{width}}/{len(trace_ids)}] {short}…  {exc}")
                pending += 1
            except Exception as exc:
                _fmt.fail(f"[{i:{width}}/{len(trace_ids)}] {short}…  {exc}")
                failure += 1
```

Initialize `pending = 0` alongside `success`/`failure`, and in the summary mention pending traces. Keep `sys.exit(1)` only when `failure > 0`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_compute_robustness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/compute.py tests/test_compute_robustness.py
git commit -m "feat(compute): --timeout flag; surface still-computing as pending, not failure"
```

---

### Task 4: Make `OPENAI_API_KEY` optional on hosted

**Files:**
- Modify: `gigaflow/commands/compute.py` (`_handle_compute`)
- Test: `tests/test_compute_robustness.py`

- [ ] **Step 1: Write failing test**

```python
def test_compute_no_openai_key_omits_from_body(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = {}
    def fake_api(base, method, path, body=None, **kw):
        if path.startswith("/flow/"):
            seen["body"] = body
            return 200, {"metrics": {"groundedness": 0.5, "tool_consumption": 0.0}, "token_usage": {}}
        if path == "/query/":
            # selection + partition queries
            if "run_id IS NOT NULL" in body["sql"]:
                return 200, {"columns": ["trace_id"], "rows": []}
            return 200, {"columns": ["trace_id"], "rows": [["t1"]]}
        return 200, {}
    monkeypatch.setattr(C, "api", fake_api)
    import argparse
    args = argparse.Namespace(sql="SELECT trace_id FROM trace_metrics", force=False,
                              concurrency=1, model=None, k_threshold=None,
                              cost_breakdown=False, timeout=None, api_key=None)
    C._handle_compute(args, "http://b")
    assert "api_key" not in seen["body"]   # OpenAI key omitted, not hard-failed
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_compute_robustness.py -k no_openai -v`
Expected: FAIL (currently `sys.exit(1)` on missing key).

- [ ] **Step 3: Implement** — replace the hard-fail block:

```python
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        _fmt.info("No OPENAI_API_KEY set — the hosted backend will use its "
                  "platform key. (Local/self-hosted backends may require one.)")
    ...
    body: dict = {}
    if openai_key:
        body["api_key"] = openai_key
```

If the backend later returns a 4xx whose detail mentions an OpenAI/api key, `_run_one` already surfaces `detail`; no extra handling needed.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_compute_robustness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/compute.py tests/test_compute_robustness.py
git commit -m "feat(compute): OPENAI_API_KEY optional; hosted uses platform key"
```

---

### Task 5: Read-after-write 404 retry helper + wire into inspect/spans

**Files:**
- Create: `gigaflow/commands/_retry.py`
- Modify: `gigaflow/commands/inspect.py`, `gigaflow/commands/traces.py`
- Test: `tests/test_readafterwrite_retry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_readafterwrite_retry.py
import gigaflow.commands._retry as R

def test_get_with_retry_recovers_from_404(monkeypatch):
    seq = [(404, {"detail": "Trace not found"}), (404, {"detail": "Trace not found"}), (200, {"ok": True})]
    calls = {"n": 0}
    def fake_api(base, method, path, **kw):
        i = min(calls["n"], len(seq) - 1); calls["n"] += 1
        return seq[i]
    monkeypatch.setattr(R, "api", fake_api)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    status, resp = R.get_with_retry("http://b", "/traces/x", None, tries=5, delay=0.01)
    assert status == 200 and resp == {"ok": True}
    assert calls["n"] == 3

def test_get_with_retry_gives_up_after_tries(monkeypatch):
    def fake_api(*a, **k): return 404, {"detail": "Trace not found"}
    monkeypatch.setattr(R, "api", fake_api)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    status, resp = R.get_with_retry("http://b", "/traces/x", None, tries=3, delay=0.01)
    assert status == 404

def test_get_with_retry_non_404_returns_immediately(monkeypatch):
    calls = {"n": 0}
    def fake_api(*a, **k):
        calls["n"] += 1; return 500, {"detail": "boom"}
    monkeypatch.setattr(R, "api", fake_api)
    status, resp = R.get_with_retry("http://b", "/traces/x", None, tries=5, delay=0.01)
    assert status == 500 and calls["n"] == 1
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_readafterwrite_retry.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — create `gigaflow/commands/_retry.py`:

```python
"""Shared GET-with-retry for read-after-write lag on by-id endpoints."""
import time
from gigaflow._http import api


def get_with_retry(base_url, path, api_key=None, tries=5, delay=2.0):
    """GET that retries ONLY on 404 (eventual consistency right after a write).

    Non-404 statuses (including connection failures / other errors) return
    immediately. Returns the final (status, payload).
    """
    status, resp = api(base_url, "GET", path, api_key=api_key)
    attempt = 1
    while status == 404 and attempt < tries:
        time.sleep(delay)
        status, resp = api(base_url, "GET", path, api_key=api_key)
        attempt += 1
    return status, resp
```

In `inspect.py` replace the two `api(base_url, "GET", f"/traces/{...}")` calls with `get_with_retry(...)` (import at top: `from gigaflow.commands._retry import get_with_retry`).

In `traces.py` `_handle_spans`, replace the `api(base_url, "GET", f"/traces/{args.trace_id}/spans", ...)` call with `get_with_retry(...)` (same import).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_readafterwrite_retry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/commands/_retry.py gigaflow/commands/inspect.py gigaflow/commands/traces.py tests/test_readafterwrite_retry.py
git commit -m "feat(inspect,spans): retry by-id GET on 404 to ride out read-after-write lag"
```

---

### Task 6: CLI polish — `--version`, vendor-neutral description, fix `run flow` hint

**Files:**
- Modify: `gigaflow/cli.py`, `gigaflow/commands/traces.py`
- Test: `tests/test_cli_polish.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_polish.py
import io, contextlib, importlib.metadata, pytest
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
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_cli_polish.py -v`
Expected: FAIL (no `--version`; `run flow` still present).

- [ ] **Step 3: Implement**

In `cli.py`, on the top-level parser add (before `parse_args`):

```python
    parser.add_argument(
        "--version", action="version",
        version=f"gigaflow {importlib.metadata.version('gigaflow')}",
    )
```

Add `import importlib.metadata` at the top. Confirm `main(argv=None)` passes `argv` to `parse_args` (if it currently calls `parse_args()` with no args, change to `parse_args(argv)` so the test can inject `["--version"]`). Update the parser `description` to vendor-neutral wording if it still says "Arize Phoenix" (e.g. "ingest LLM/agent traces from your observability platform and compute Flow analysis").

In `traces.py`, change the hint line from `gigaflow run flow <trace_id>` to:
`gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_cli_polish.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gigaflow/cli.py gigaflow/commands/traces.py tests/test_cli_polish.py
git commit -m "feat(cli): --version; vendor-neutral description; fix stale 'run flow' hint"
```

---

### Task 7: Full suite + manual smoke

- [ ] **Step 1:** Run the new unit tests: `uv run pytest tests/test_compute_robustness.py tests/test_readafterwrite_retry.py tests/test_cli_polish.py -v` — all PASS.
- [ ] **Step 2:** Run the broader logic suite (excluding the pip-dependent `installed_cli` subprocess tests): `uv run pytest tests -v -k "not installed_cli"` — no regressions among collectible tests.
- [ ] **Step 3:** `gigaflow --version` prints the version; `gigaflow compute --help` shows `--timeout`.
- [ ] **Step 4: Commit any fixups.**

---

## Self-Review

- **Spec coverage:** compute 504/timeout poll (T1–T3) ✓; no-dup-run assertion (T2) ✓; deadline message (T1/T3) ✓; OPENAI optional (T4) ✓; read-after-write retry (T5) ✓; `run flow` hint (T6) ✓; `--version`/description (T6) ✓. `.env.example`, `QUERYING.md`, and backend `api_key` redaction are in the **gigaflow repo** and handled by a separate parallel worktree/PR (out of this plan's file scope), per the spec's Rollout section.
- **Placeholders:** none — every code step is concrete.
- **Type consistency:** `_poll_for_run` returns `(groundedness, tool_consumption, usage_dict)` matching `_run_one`'s contract; `ComputeStillRunning` defined in T1, caught in T3; `get_with_retry` signature consistent across T5 uses.
