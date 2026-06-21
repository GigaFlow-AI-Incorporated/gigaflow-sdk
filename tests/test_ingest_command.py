"""End-to-end tests for `gigaflow ingest` (subprocess against the mock server)."""

import json

from _constants import MOCK_TRACE_ID
from conftest import _MockAPIHandler
from test_commands import err, out, run


def _write_trace(tmp_path, blob) -> str:
    f = tmp_path / "trace.json"
    f.write_text(json.dumps(blob))
    return str(f)


_OTLP_BLOB = {"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "ab", "spanId": "cd"}]}]}]}


class TestIngest:
    def test_ingest_waits_and_prints_viewer_link(self, installed_cli, mock_server, clean_env, tmp_path):
        """Happy path: 202 → poll running → complete → absolute viewer link."""
        _MockAPIHandler.ingest_status_polls = 0
        path = _write_trace(tmp_path, _OTLP_BLOB)
        result = run(["--backend", mock_server, "ingest", path, "--no-browser"], clean_env, timeout=30)
        stdout = out(result)
        assert result.returncode == 0, err(result)
        assert "Trace ingested" in stdout
        assert "Flow analysis complete" in stdout
        root = mock_server.replace("/api/v1", "")
        assert f"{root}/flow/{MOCK_TRACE_ID}" in stdout
        # The CLI forwarded the parsed blob + exporter to the backend.
        assert _MockAPIHandler.last_ingest_body["blob"] == _OTLP_BLOB
        assert _MockAPIHandler.last_ingest_body["exporter"] == "auto"
        assert _MockAPIHandler.ingest_status_polls >= 2

    def test_ingest_no_wait_skips_polling(self, installed_cli, mock_server, clean_env, tmp_path):
        _MockAPIHandler.ingest_status_polls = 0
        path = _write_trace(tmp_path, _OTLP_BLOB)
        result = run(["--backend", mock_server, "ingest", path, "--no-wait", "--no-browser"], clean_env)
        stdout = out(result)
        assert result.returncode == 0, err(result)
        assert "still running" in stdout
        assert f"/flow/{MOCK_TRACE_ID}" in stdout
        assert _MockAPIHandler.ingest_status_polls == 0

    def test_ingest_stdin(self, installed_cli, mock_server, clean_env):
        result = run(
            ["--backend", mock_server, "ingest", "-", "--no-wait", "--no-browser"],
            clean_env,
            stdin=json.dumps(_OTLP_BLOB).encode(),
        )
        assert result.returncode == 0, err(result)
        assert f"/flow/{MOCK_TRACE_ID}" in out(result)

    def test_ingest_label_and_exporter_forwarded(self, installed_cli, mock_server, clean_env, tmp_path):
        path = _write_trace(tmp_path, _OTLP_BLOB)
        result = run(
            ["--backend", mock_server, "ingest", path, "--no-wait", "--no-browser",
             "--exporter", "logfire", "--label", "my-run"],
            clean_env,
        )
        assert result.returncode == 0, err(result)
        assert _MockAPIHandler.last_ingest_body["exporter"] == "logfire"
        assert _MockAPIHandler.last_ingest_body["trace_label"] == "my-run"

    def test_ingest_project_forwarded(self, installed_cli, mock_server, clean_env, tmp_path):
        """--project forwards project_id so the backend classifies with that
        project's transform config (instead of an auto-detected bundled one)."""
        path = _write_trace(tmp_path, _OTLP_BLOB)
        result = run(
            ["--backend", mock_server, "ingest", path, "--no-wait", "--no-browser",
             "--project", "11111111-1111-1111-1111-111111111111"],
            clean_env,
        )
        assert result.returncode == 0, err(result)
        assert _MockAPIHandler.last_ingest_body["project_id"] == "11111111-1111-1111-1111-111111111111"

    def test_ingest_omits_project_id_by_default(self, installed_cli, mock_server, clean_env, tmp_path):
        path = _write_trace(tmp_path, _OTLP_BLOB)
        result = run(["--backend", mock_server, "ingest", path, "--no-wait", "--no-browser"], clean_env)
        assert result.returncode == 0, err(result)
        assert "project_id" not in _MockAPIHandler.last_ingest_body

    def test_ingest_duplicate_reuses_existing(self, installed_cli, mock_server, clean_env, tmp_path):
        path = _write_trace(tmp_path, {"_mock": "duplicate"})
        result = run(["--backend", mock_server, "ingest", path, "--no-browser"], clean_env)
        stdout = out(result)
        assert result.returncode == 0, err(result)
        assert "already ingested" in stdout
        assert f"/flow/{MOCK_TRACE_ID}" in stdout

    def test_ingest_typed_rejection(self, installed_cli, mock_server, clean_env, tmp_path):
        """A 422 prints the backend's human-readable reason and exits 1."""
        path = _write_trace(tmp_path, {"_mock": "reject"})
        result = run(["--backend", mock_server, "ingest", path, "--no-browser"], clean_env)
        assert result.returncode == 1
        assert "no spans" in err(result).lower()

    def test_ingest_invalid_json(self, installed_cli, mock_server, clean_env, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json {")
        result = run(["--backend", mock_server, "ingest", str(bad), "--no-browser"], clean_env)
        assert result.returncode == 1
        assert "not valid JSON" in err(result)

    def test_ingest_missing_file(self, installed_cli, mock_server, clean_env):
        result = run(["--backend", mock_server, "ingest", "/nope/missing.json", "--no-browser"], clean_env)
        assert result.returncode == 1
        assert "Could not read" in err(result)

    def test_ingest_auth_failure_hints_login(self, installed_cli, mock_server, clean_env, tmp_path):
        path = _write_trace(tmp_path, _OTLP_BLOB)
        result = run(
            ["--backend", mock_server, "--api-key", "FORCE401", "ingest", path, "--no-browser"],
            clean_env,
        )
        assert result.returncode == 1
        assert "gigaflow login" in err(result)


class TestSyncTraceLinks:
    def test_sync_prints_per_trace_viewer_links(self, installed_cli, mock_server, configured_env):
        result = run(["--backend", mock_server, "sync"], configured_env)
        stdout = out(result)
        assert result.returncode == 0, err(result)
        root = mock_server.replace("/api/v1", "")
        assert f"{root}/flow/{MOCK_TRACE_ID}" in stdout
