"""ingest command — analyze a local OTel trace export and get a viewer link.

The minimal-friction path into GigaFlow: no vendor account, no datasource, no
token minting. Point the command at an exported OTel trace (OTLP/JSON envelope
or a flat span array), and the backend auto-provisions a project, runs Flow
analysis in the background, and returns a viewer link.

    gigaflow ingest trace.json
    curl https://my-collector/export | gigaflow ingest -

Wraps ``POST /api/v1/ingest/otel`` (the same endpoint behind the website's
Analyze tab) and polls ``GET /api/v1/ingest/otel/status/{flow_run_id}`` until
the Flow run completes, then prints and opens the ``/flow/{trace_id}`` viewer.
"""

import json
import sys
import time

from gigaflow import _fmt
from gigaflow._http import api, unreachable_hint

# Exporter choices mirror the backend's OtelIngestRequest contract.
_EXPORTERS = ["auto", "arize", "logfire", "mlflow", "braintrust", "weave", "generic"]

_POLL_INTERVAL = 3.0
# Flow runs minutes on big traces; the run continues server-side regardless —
# on timeout we hand the user the viewer link instead of failing.
_POLL_TIMEOUT = 900.0


def register(sub) -> None:
    p = sub.add_parser(
        "ingest",
        help="Analyze a local OTel trace export (JSON) and get a Flow viewer link",
    )
    p.add_argument(
        "file",
        help="Path to an OTel JSON export (OTLP envelope or flat span array). Use '-' to read stdin.",
    )
    p.add_argument(
        "--exporter",
        default="auto",
        choices=_EXPORTERS,
        help="Which SDK produced the trace (default: auto-detect)",
    )
    p.add_argument("--label", default=None, help="Optional trace name shown in the dashboard")
    p.add_argument(
        "--project",
        default=None,
        metavar="ID",
        help="Ingest into an existing project and classify with ITS transform config, "
        "instead of auto-detecting a bundled transform. Use for traces whose convention "
        "no built-in exporter matches (e.g. a custom span.type mapping).",
    )
    p.add_argument(
        "--no-wait",
        action="store_true",
        help="Print the viewer link immediately instead of waiting for Flow analysis",
    )
    p.add_argument("--no-browser", action="store_true", help="Print viewer URL but do not open browser")
    p.set_defaults(func=_handle_ingest)


# ── Handler ─────────────────────────────────────────────────────────────────

def _handle_ingest(args, base_url: str) -> None:
    _fmt.header("GigaFlow Ingest")

    blob = _read_blob(args.file)

    _fmt.section("Uploading trace")
    body = {"blob": blob, "exporter": args.exporter}
    if args.label:
        body["trace_label"] = args.label
    if args.project:
        body["project_id"] = args.project
    status, resp = api(
        base_url, "POST", "/ingest/otel", body=body, api_key=getattr(args, "api_key", None)
    )

    if status is None:
        _fmt.fail(unreachable_hint(base_url))
        sys.exit(1)
    if status in (401, 403):
        _fmt.fail("Authentication failed — run 'gigaflow login' (or pass --api-key).")
        sys.exit(1)
    if status in (400, 422):
        # Typed rejection: the backend explains exactly why the paste is
        # unanalysable ({reason, message, detected_exporter}); no trace written.
        _fmt.fail(resp.get("message") or resp.get("detail") or str(resp))
        if resp.get("detected_exporter"):
            _fmt.info(f"Detected exporter: {resp['detected_exporter']}")
        if resp.get("reason") in ("ambiguous_needs_exporter", "not_classified"):
            _fmt.info("Try again with an explicit exporter, e.g.:  gigaflow ingest "
                      f"{args.file} --exporter logfire")
        sys.exit(1)
    if status not in (200, 202):
        _fmt.fail(f"Ingest failed ({status}): {resp}")
        sys.exit(1)

    trace_id = resp.get("trace_id")
    viewer_url = _absolute_viewer_url(base_url, resp.get("viewer_url"), trace_id)

    if resp.get("already_ingested"):
        _fmt.ok("This trace was already ingested — reusing the existing analysis.")
    else:
        _fmt.ok(f"Trace ingested (exporter: {resp.get('detected_exporter', 'unknown')})")
    _fmt.info(f"Trace ID: {trace_id}")

    run_status = resp.get("status")
    if not args.no_wait and resp.get("flow_run_id") and run_status not in ("complete", "error"):
        run_status = _wait_for_flow(args, base_url, resp["flow_run_id"])

    print()
    if run_status == "complete":
        _fmt.ok("Flow analysis complete.")
    elif run_status == "error":
        _fmt.warn("Flow analysis failed — the trace and its spans are still viewable.")
    else:
        _fmt.info("Flow analysis is still running; the viewer updates when it finishes.")
    _fmt.info(f"Viewer: {viewer_url}")
    if not args.no_browser:
        from gigaflow.commands.inspect import _open_browser

        _open_browser(viewer_url)
    print()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_blob(path: str):
    """Read and parse the OTel JSON export from a file or stdin ('-')."""
    try:
        raw = sys.stdin.read() if path == "-" else open(path).read()
    except OSError as e:
        _fmt.fail(f"Could not read {path}: {e}")
        sys.exit(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _fmt.fail(f"{path} is not valid JSON: {e}")
        _fmt.info("Expected an OTLP/JSON envelope (resourceSpans) or a flat span array.")
        sys.exit(1)


def _absolute_viewer_url(base_url: str, viewer_path: str | None, trace_id: str | None) -> str:
    """The backend returns a relative viewer path; anchor it to the backend host."""
    root = base_url.replace("/api/v1", "").rstrip("/")
    return f"{root}{viewer_path or f'/flow/{trace_id}'}"


def _wait_for_flow(args, base_url: str, flow_run_id: str) -> str:
    """Poll the Flow run status until complete/error or timeout.

    Transient poll failures (gateway timeouts, blips) are tolerated — the run
    proceeds server-side either way, so we only give up on a hard 404 (unknown
    run) or the overall timeout.
    """
    _fmt.section("Running Flow analysis")
    _fmt.info("Analyzing how tool outputs ground the agent's responses…")
    deadline = time.monotonic() + _POLL_TIMEOUT
    last = "queued"
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)
        status, resp = api(
            base_url,
            "GET",
            f"/ingest/otel/status/{flow_run_id}",
            api_key=getattr(args, "api_key", None),
        )
        if status == 404:
            _fmt.warn("Flow run not found — it may have been cleaned up.")
            return last
        if status != 200:
            continue  # transient — keep polling
        last = resp.get("status", last)
        if last in ("complete", "error"):
            return last
    _fmt.warn("Timed out waiting for Flow analysis — it continues in the background.")
    return last
