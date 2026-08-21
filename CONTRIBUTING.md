# Contributing

## Where to start

1. Read the [README](README.md) for the product story, diagrams, and install steps.
2. Read [docs/architecture.md](docs/architecture.md) for the folder map and request lifecycle.
3. The server entrypoint is `python -m mainframe_workflow_mcp.server`.

## Dev setup

Same as the README install: Python 3.11+, Node.js, a Zowe profile, and GitHub access to the private Zcrafter dependency.

```bash
python -m venv .venv
# Windows: .venv\Scripts\pip install -r requirements-dev.txt
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements-dev.txt

cd credential-resolver && npm install && npm run build && cd ..
cp .env.example .env
```

## Tests

```bash
pytest -v
cd credential-resolver && npm test && cd ..
```

Unit tests do not need a live mainframe. The optional live smoke script is `scripts/live_zowe_sdk_tools.py` (needs real z/OSMF credentials).

## Local-only paths (not in git)

On a maintainer checkout you may still see:

- `docs/superpowers/` — internal design notes and task reports
- `mainframe_mcp/` — a separate read-only assistant, not part of this public project

Those directories are gitignored. Do not add them in a pull request.
