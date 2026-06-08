# Changelog

All notable changes to the `gigaflow` CLI are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-06-07

### Changed

- The CLI now defaults to the hosted backend (`https://api.gigaflow.io/api/v1`),
  so `pip install gigaflow && gigaflow login` works out of the box.

## [0.3.0] - 2026-06-07

### Added

- Per-user accounts: `gigaflow login` / `logout` / `whoami`. `login` opens a
  browser sign-in (email + password) and captures the session back to the CLI
  via a one-shot local callback; credentials are stored in
  `~/.gigaflow/credentials.json` (mode 0600) with automatic token refresh.
- Logged-in uploads are attributed to your account; the web UI shows only your
  traces. Credential precedence: explicit `--api-key` > env > logged-in user
  token > saved static key.

## [0.2.1] - 2026-06-06

### Changed

- Version bump to publish the first release under the new PyPI project
  ownership. No functional changes since 0.2.0.

## [0.2.0] - 2026-05-29

### Added

- **Hosted-backend support.** Point the CLI at any GigaFlow backend. The backend
  URL resolves as `--backend` > `$GIGAFLOW_BACKEND_URL` > saved config
  `backend_url` > a built-in default.
- **API-key authentication.** Supply a GigaFlow API key via `--api-key`,
  `$GIGAFLOW_API_KEY`, or the saved config `api_key` field (resolved in that
  order). When present it is forwarded on every request as
  `Authorization: Bearer <key>`, satisfying the backend's protected Flow compute
  endpoint.
- `gigaflow setup` now prompts for the backend URL (defaulting to the current
  resolved value) and an optional API key, persisting both to
  `~/.gigaflow/config.json`.
- New `api_key` config key and `_config.get` / `_config.set` helpers.

### Changed

- **Resilient HTTP.** Requests now use a 30 s timeout and retry idempotent
  GET/HEAD/OPTIONS calls and connection errors up to three times with
  exponential backoff. HTTP error responses (4xx/5xx) are never retried so
  authentication failures surface immediately.
- Unreachable-backend and authentication failures now print a short, actionable
  message instead of a Python traceback.

### Notes

- The CLI remains **zero-dependency** (Python standard library only).
- `gigaflow compute` continues to forward your `OPENAI_API_KEY` in the request
  body for the backend's Flow LLM calls — this is separate from the GigaFlow API
  key carried in the `Authorization` header.

## [0.1.0]

- Initial release: connect Arize Phoenix traces to GigaFlow, sync, query
  `trace_metrics`, compute Flow, and inspect traces in the browser viewer.
