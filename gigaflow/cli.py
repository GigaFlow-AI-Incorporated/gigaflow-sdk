"""
gigaflow — CLI entry point.

Commands:
  gigaflow setup                     Configure GigaFlow with a tracing datasource (Arize, Braintrust, Logfire, MLflow, W&B Weave)
  gigaflow sync                      Re-sync traces from the configured datasource
  gigaflow ui                        Open the traces dashboard in the browser
  gigaflow traces                    List all traces (auto-syncs first)
  gigaflow spans <trace_id>          List spans for a trace
  gigaflow query "<SQL>"             Run SQL SELECT against the trace_metrics view
  gigaflow compute "<SQL>"           Batch-compute Flow for traces matching a SQL query
  gigaflow supplement [SESSION_ID]   Enrich Claude Code spans with local JSONL content
  gigaflow inspect <trace_id>        Visualize a single trace (opens Flow viewer)
  gigaflow projects                  List all projects
  gigaflow config show               Show saved configuration
  gigaflow config clear              Clear saved configuration
"""

import argparse
import importlib.metadata
import os
import sys

from gigaflow import _auth, _config, _fmt
from gigaflow._setup import load_env_file
from gigaflow.commands import (
    auth as auth_cmd,
    compute,
    config,
    inspect,
    projects,
    query,
    setup,
    supplement,
    traces,
    ui,
)


def _resolve_credential(flag, env_key, user_token, config_key):
    """Bearer credential precedence: explicit flag > env static > user token > config key.

    The user token (a Supabase JWT from `gigaflow login`) is preferred over the
    saved static config key, but an explicit --api-key or env key still wins so
    self-host/CI overrides keep working.
    """
    return flag or env_key or user_token or config_key or None


# Hosted backend — the default so `pip install gigaflow && gigaflow login` works
# out of the box. Local dev overrides via --backend / $GIGAFLOW_BACKEND_URL.
DEFAULT_BACKEND_URL = "https://api.gigaflow.io/api/v1"


def _resolve_backend_url(flag, env_val, config_val):
    """Backend URL precedence: --backend > $GIGAFLOW_BACKEND_URL > saved config > hosted default."""
    return (flag or env_val or config_val or DEFAULT_BACKEND_URL).rstrip("/")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gigaflow",
        description="GigaFlow CLI — ingest LLM/agent traces from your observability platform and compute Flow analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  gigaflow setup
  gigaflow sync
  gigaflow traces
  gigaflow spans <trace_id>
  gigaflow query "SELECT trace_id, trace_name, groundedness FROM trace_metrics"
  gigaflow query --examples
  gigaflow compute "SELECT trace_id FROM trace_metrics WHERE run_id IS NULL"
  gigaflow compute "SELECT trace_id FROM trace_metrics WHERE env = 'prod'" --force
  gigaflow ui
  gigaflow inspect <trace_id>
  gigaflow inspect <trace_id> --cli
  gigaflow config show
  gigaflow config clear
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gigaflow {importlib.metadata.version('gigaflow')}",
    )
    parser.add_argument(
        "--backend",
        metavar="URL",
        default=None,
        help=(
            "GigaFlow API base URL. Overrides $GIGAFLOW_BACKEND_URL and the saved "
            "config (default: https://api.gigaflow.io/api/v1). For local dev, pass "
            "--backend http://localhost:8000/api/v1 or set $GIGAFLOW_BACKEND_URL."
        ),
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        default=None,
        help=(
            "GigaFlow API key, sent as 'Authorization: Bearer <key>'. "
            "Overrides $GIGAFLOW_API_KEY and the saved config."
        ),
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        default=None,
        help="Path to gigaflow.env (default: auto-detects gigaflow.env in current directory)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    auth_cmd.register(sub)
    setup.register(sub)
    traces.register(sub)
    inspect.register(sub)
    ui.register(sub)
    projects.register(sub)
    config.register(sub)
    query.register(sub)
    compute.register(sub)
    supplement.register(sub)

    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    # Load gigaflow.env and inject keys into os.environ (without overriding existing vars)
    env_file = args.env_file or ("gigaflow.env" if os.path.exists("gigaflow.env") else None)
    if env_file:
        for key, value in load_env_file(env_file).items():
            os.environ.setdefault(key, value)

    cfg = _config.load()
    # --backend > $GIGAFLOW_BACKEND_URL > cfg backend_url > hosted default.
    base_url = _resolve_backend_url(
        args.backend, os.environ.get("GIGAFLOW_BACKEND_URL"), cfg.get("backend_url")
    )

    # API-key resolution order:
    #   --api-key > $GIGAFLOW_API_KEY > $GIGAFLOW_FLOW_API_KEY > user_token > cfg api_key > None
    # GIGAFLOW_FLOW_API_KEY mirrors the backend's documented client var
    # (backend/CLAUDE.md). GIGAFLOW_API_KEY is the preferred general name now
    # that the whole API surface — not just Flow compute — is token-gated. Both
    # forward the same value as `Authorization: Bearer <key>`.
    # user_token is the Supabase JWT from `gigaflow login`; it is preferred over
    # the saved static config key, but explicit flags/env vars still win for CI.
    # Stashed back onto args so each handler can forward it to _http.api().
    user_token = _auth.access_token(base_url)
    args.api_key = _resolve_credential(
        flag=args.api_key,
        env_key=os.environ.get("GIGAFLOW_API_KEY") or os.environ.get("GIGAFLOW_FLOW_API_KEY"),
        user_token=user_token,
        config_key=cfg.get("api_key"),
    )

    _BACKEND_CMDS = {"traces", "spans", "supplement", "sync", "query", "projects", "compute", "ui"}
    if args.api_key is None and getattr(args, "command", None) in _BACKEND_CMDS:
        # To stderr, not stdout: a stdout hint would corrupt machine-readable
        # output such as `gigaflow query --json`.
        print("  You're not signed in. Run: gigaflow login  (opens your browser to sign in)", file=sys.stderr)

    args.func(args, base_url)


if __name__ == "__main__":
    main()
