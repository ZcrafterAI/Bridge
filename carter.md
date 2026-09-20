# carter branch — what changed and why

Bridge's role in the target architecture: **Z Xplore (dev z/OS) → bridge (this repo, MCP server) → backend → redaction service → Anthropic**. Bridge is the only thing that talks to z/OS directly (via the Zowe SDK); everything else is a hop downstream of it.

This branch takes bridge from "spawned as a stdio subprocess under a coding CLI, with its own internal spec/plan/approval workflow engine" to "a real network MCP service that executes typed tools and trusts backend's permission gate, one hop up." 6 commits, net **-960 lines**.

Verification standard for every commit below: full pytest suite green, plus a **live integration test** against the real deployed stack (real backend, real Z Xplore) — not just unit tests in isolation.

---

## 1. Switch bridge to Streamable HTTP MCP transport
**Files:** `mainframe_workflow_mcp/config.py`, `mainframe_workflow_mcp/server.py`, `.env.example`, `README.md`

Bridge previously defaulted to stdio transport (spawned as a subprocess under a coding CLI). backend's mcp-go client needs a real network service. Added `MCP_TRANSPORT`/`MCP_HOST`/`MCP_PORT`/`MCP_PATH` config and switched `mcp.run(...)` to bind `transport="http"` on a port. Verified live: a real MCP `initialize` call answers 200 OK over the network.

## 2. Remove bridge's internal spec/plan/approval-gate workflow engine
**Files:** `mainframe_workflow_mcp/{requests,lifecycle}.py` (deleted), `db.py` (-202 lines), `server.py`, `proxy.py`, `.claude/skills/mainframe-workflow/SKILL.md` (deleted), `docs/architecture.md`, `README.md`, `CONTRIBUTING.md`

Bridge used to run its **own** multi-step spec → plan → approve → execute workflow (tied to a `request_id`), independently of backend's permission system — one of three incompatible approval mechanisms across the stack (bridge, backend, CLI all had their own). Removed entirely: bridge now just executes typed tools tagged `approval: never|required` and trusts that whatever calls it (backend) has already gated "required" calls. `db.py`'s SQLite is `action_log`-only now — no more raw request/spec/plan text persisted, no plaintext markdown archive (`lifecycle.py`'s job). This is the single biggest change in the diff.

**Why it matters for the team:** if you're used to bridge having its own approval workflow / `request_id` concept, that's gone — bridge is a pure executor now, approval lives one hop up in backend.

## 3. Add env-based credential source for containerized bridge
**Files:** `mainframe_workflow_mcp/config.py`, `mainframe_workflow_mcp/credentials.py` (new), `tests/test_credentials.py` (new), `.env.example`, `README.md`, `docs/architecture.md`

The existing credential-resolver path needs an OS keychain, which a container doesn't have. Added `MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE=env`, which reads `ZOSMF_HOST`/`_PORT`/`_USER`/`_PASSWORD`/`_PROTOCOL`/`_REJECT_UNAUTHORIZED` straight from the environment — this is how the deployed bridge pod gets real Z Xplore credentials (fed by a K8s Secret, never committed).

## 4. Add Dockerfile for bridge
**Files:** `Dockerfile` (new), `.dockerignore` (new), `README.md`

Python-only image (`python:3.11-slim`) — no Node/keytar, since the env-based credential path (#3) doesn't need the OS-keychain resolver. Verified: builds, runs, answers a live MCP call with dummy Xplore-shaped credentials.

**Note if you rebuild this locally:** `docker build` prints a `SecretsUsedInArgOrEnv` warning on the `MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE` env line — this is a linter false positive. That variable's value is the literal string `"env"` (a mode selector meaning "read credentials from the environment"), not an actual secret. No real credential value is baked into the image; real values only ever arrive via a K8s Secret at deploy time.

## 5. Clamp job.wait polling and document Z Xplore as shared/rate-limited
**Files:** `mainframe_workflow_mcp/clients/zowe_sdk.py`, `mainframe_workflow_mcp/toolbox/contract.py`, `tests/test_zowe_sdk_client.py` (new), `README.md`, `CONTRIBUTING.md`

**IBM Z Xplore is a shared, multi-tenant learning environment, not a private sandbox** — flagged explicitly so nobody points automated/scripted test loops at it. `job.wait`'s polling is now hard-clamped server-side regardless of what a caller (or a model choosing tool args) requests: `_WAIT_MIN_DELAY_SECONDS = 1.0`, `_WAIT_MAX_ATTEMPTS = 60`. This is a concrete guardrail, not just a policy note in a doc.

## 6. Set standard readOnlyHint/destructiveHint MCP annotations on tools
**Files:** `mainframe_workflow_mcp/proxy.py`, `tests/test_credentials.py`, `tests/test_workflow_proxy_{mutating,readonly}.py`

Backend needs a way to know, per-tool, whether to dispatch immediately or gate for approval. Rather than inventing a bespoke field, bridge now sets the **standard** MCP `ToolAnnotations(readOnlyHint=..., destructiveHint=...)` derived directly from each tool's existing `approval: never|required` flag in `toolbox/contract.py` — one source of truth, exposed the way any MCP client (not just this specific backend) would expect to read it.

---

## Also fixed while touching this code (not a scope change)
- A pre-existing break against current `fastmcp`: `fastmcp.tools.tool.Tool` no longer exists in fastmcp 4.0.5 — moved to `from fastmcp.tools import Tool`. Was blocking the entire test suite before any of the above started.
- `test_credentials.py`'s resolver-path tests weren't pinning `CREDENTIAL_SOURCE`, so they broke once a real `.env` with `CREDENTIAL_SOURCE=env` existed on disk — test isolation fix, not a behavior change.
- Two lingering `Tool.inputSchema` accesses in `tests/test_workflow_proxy_{mutating,readonly}.py` were hitting a `FastMCPDeprecationWarning` (MCP SDK v2 renamed it to `.input_schema`) — updated both call sites, no behavior change, just silences the warning on every test run going forward.

## Architectural note worth knowing
`proxy.py`'s `_make_impl()` hardcodes `"approved": True` on every tool call it builds (see the comment at that call site). This looks alarming out of context, but it's intentional: `toolbox/executor.py`'s internal `approved` check is a leftover from a different design/test harness, and by the time any call reaches this proxy layer, backend has already gated it (or it was never gated, for a read-only tool) — bridge doesn't second-guess the caller. Confirmed via a live test: a real `dataset.create` call correctly blocked on backend's permission gate *before* ever reaching bridge, and only ran once approved.

## Verification
- Full test suite: **48/48 passing**, zero warnings (as of this pass — the two deprecation warnings above were fixed here).
- `docker build` succeeds (one expected linter false-positive noted above, not a real issue).
- No secrets committed at any point — `.env` gitignored and confirmed untracked throughout; real Z Xplore credentials only ever exist in a local, gitignored `.env` or a K8s Secret.
- Live end-to-end confirmed against the real deployed stack: backend successfully discovers and calls bridge's tools over the network against **real Z Xplore** (`bridge_profile_list`, `bridge_connection_verify` returning real z/OS version data), and a write-capable call (`bridge_dataset_create`) correctly gated by backend, then executed against the real Xplore instance once approved.
