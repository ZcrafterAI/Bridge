# Contributing

## Where to start

1. Read the [README](README.md) for the product story, diagrams, and install steps.
2. Read [docs/architecture.md](docs/architecture.md) for the folder map and how approval works.
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

Unit tests do not need a live mainframe. There is no live-mainframe smoke script in this repo yet (a pre-existing doc referenced one under `scripts/`; that directory doesn't exist) — testing against a real z/OSMF target currently means running the server itself against Z Xplore.

**If that target is IBM Z Xplore: it's a shared, multi-tenant learning environment, not a private sandbox.** Run manual, occasional checks against it — never wire it into CI or any automated/repeated test loop, and don't add a live-test script here that would run on every push. If you're building one for occasional manual use, keep it deliberately light (few calls, sane delays); `job.wait`'s polling is already clamped server-side for this reason (see `clients/zowe_sdk.py`).

## Local-only paths (not in git)

On a maintainer checkout you may still see:

- `docs/superpowers/` — internal design notes and task reports
- `mainframe_mcp/` — a separate read-only assistant, not part of this public project

Those directories are gitignored. Do not add them in a pull request.
