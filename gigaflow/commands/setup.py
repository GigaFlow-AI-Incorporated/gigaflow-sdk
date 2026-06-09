"""setup / sync commands."""

import sys

from gigaflow import _config, _fmt
from gigaflow._http import api
from gigaflow._setup import do_sync, run_wizard
from gigaflow.commands.auth import ensure_authenticated

# How many fresh per-trace viewer links to print after a sync.
_SYNC_LINKS_SHOWN = 5


def register(sub) -> None:
    sub.add_parser("setup", help="Configure GigaFlow with a tracing datasource (Arize, Braintrust, Logfire, MLflow, W&B Weave)").set_defaults(func=_handle_setup)
    sub.add_parser("sync",  help="Re-sync traces from the configured datasource").set_defaults(func=_handle_sync)


def _handle_setup(args, base_url: str) -> None:
    config = _config.load()
    if config.get("datasource_id"):
        print(f"  Already configured (project: {config.get('project_id', '?')[:8]}…)")
        print("  To reconfigure, run:  gigaflow config clear  then  gigaflow setup")
        print()
        return
    api_key = ensure_authenticated(base_url, getattr(args, "api_key", None))
    if not api_key:
        _fmt.fail("Sign-in required to run setup. Run:  gigaflow login")
        sys.exit(1)
    result = run_wizard(base_url, api_key)
    if result is None:
        sys.exit(1)
    _fmt.section("Next steps")
    print()
    print("  gigaflow traces")
    print("  gigaflow spans <trace_id>")
    print("  gigaflow sync")
    print(f"  {base_url.replace('/api/v1', '')}/api/v1/docs")
    print()


def _handle_sync(args, base_url: str) -> None:
    config = _config.load()
    if not config.get("datasource_id"):
        _fmt.fail("No configuration found. Run:  gigaflow setup")
        sys.exit(1)
    _fmt.header("GigaFlow Sync")
    _fmt.section("Syncing")
    result = do_sync(base_url, config["datasource_id"], getattr(args, "api_key", None))
    if result is None:
        sys.exit(1)
    synced_traces, _ = result
    if synced_traces:
        _print_trace_links(args, base_url, config, synced_traces)
    ui_url = base_url.replace("/api/v1", "").rstrip("/") + "/"
    _fmt.info(f"Dashboard: {ui_url}")
    print("  Open the dashboard to browse traces and run Flow analysis.")
    print("  Or run:  gigaflow ui")
    print()


def _print_trace_links(args, base_url: str, config: dict, synced_traces: int) -> None:
    """Best-effort: print direct viewer links for the freshest synced traces.

    The sync report carries counts, not ids, so we read the newest traces back
    (the list endpoint orders by started_at desc). Any failure here is silently
    skipped — the sync itself already succeeded.
    """
    project_id = config.get("project_id")
    limit = min(synced_traces, _SYNC_LINKS_SHOWN)
    path = f"/traces/?limit={limit}" + (f"&project_id={project_id}" if project_id else "")
    status, resp = api(base_url, "GET", path, api_key=getattr(args, "api_key", None))
    if status != 200:
        return
    traces = resp.get("traces", resp) if isinstance(resp, dict) else resp
    if not isinstance(traces, list) or not traces:
        return
    root = base_url.replace("/api/v1", "").rstrip("/")
    _fmt.section("View your traces")
    for trace in traces[:limit]:
        trace_id = trace.get("trace_id")
        if not trace_id:
            continue
        name = trace.get("trace_name") or trace_id
        print(f"  {str(name)[:40]:<42}{root}/flow/{trace_id}")
    if synced_traces > limit:
        _fmt.info(f"…and {synced_traces - limit} more — run: gigaflow traces")
