# Contributing

## Where to start

1. Read the [README](README.md) for the product story, diagrams, and install steps.
2. Read [docs/architecture.md](docs/architecture.md) for the folder map and request lifecycle.
3. The server entrypoint is `python -m mainframe_workflow_mcp.server`.

## Dev setup

Same as the README install: Python 3.11+ and Node.js. The tests need no Zowe profile and no mainframe.

```bash
python -m venv .venv
# Windows: .venv\Scripts\pip install -r requirements-dev.txt
# macOS/Linux:
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Releasing

1. Set the same version in `pyproject.toml` and in both places in `server.json`.
2. Commit, then tag and push: `git tag v0.3.0 && git push origin v0.3.0`.
3. `.github/workflows/release.yml` runs the tests, publishes to PyPI and publishes `server.json` to the official MCP Registry.

PyPI trusts this repository's `release.yml` through a trusted publisher (owner `ZcrafterAI`, repository `Bridge`, environment `pypi`), so no token is stored anywhere. The registry step signs in with GitHub's identity for this repository.

## Tests

```bash
pytest -v
```

Unit tests do not need a live mainframe. The optional live smoke script is `scripts/live_zowe_sdk_tools.py` (needs real z/OSMF credentials).

## Local-only paths (not in git)

On a maintainer checkout you may still see:

- `docs/superpowers/` — internal design notes and task reports
- `mainframe_mcp/` — a separate read-only assistant, not part of this public project

Those directories are gitignored. Do not add them in a pull request.
