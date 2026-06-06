# Publishing the CLI to PyPI

The CLI is intended to be `pip install gigaflow`. Until the first publish:

1. Reserve the `gigaflow` name on PyPI and create an API token (stored in the
   company 1Password vault).
2. Add the token as a GitHub Actions secret and enable the publish workflow
   (tracked in the infra/admin checklist, Tier 4).
3. Tag a release; CI builds the sdist/wheel and publishes.

Until then, install from source: `pip install -e .` (see the README).
