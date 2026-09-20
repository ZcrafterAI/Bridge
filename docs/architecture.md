# Architecture

This is the developer map for **Mainframe Workflow MCP** ("bridge" in the wider ZCrafter system). Users should start at the [README](../README.md). Contributors should start at [CONTRIBUTING.md](../CONTRIBUTING.md), then this file.

## Where this sits in ZCrafter

Bridge is one of four components in the ZCrafter PoC: `backend` is the orchestrator and the only thing that talks to bridge; bridge's only job is to expose typed, real mainframe tools over MCP. Approval gating, the agent loop, and any spec/plan workflow live in backend, not here — bridge does not gate its own calls.

```
backend (MCP client, Streamable HTTP)
   │
   ▼
mainframe_workflow_mcp (bridge)
   ├─ typed tools, each tagged approval: "never" | "required"
   ├─ SQLite action log (tool/target/status only, sanitized input — never raw job content)
   └─ proxied zcrafter tools
          ▼
   zcrafter_mainframe (private library) or the bundled reference toolbox
          ▼
   Zowe Python SDK → z/OSMF → your z/OS system (IBM Z Xplore in dev)
```

## Where to look first

| If you want to understand… | Open |
|---|---|
| Tool registration + MCP transport | [`mainframe_workflow_mcp/server.py`](../mainframe_workflow_mcp/server.py) |
| How zcrafter tools are wrapped for MCP | [`mainframe_workflow_mcp/proxy.py`](../mainframe_workflow_mcp/proxy.py) |
| Tool catalog + approval flags | [`mainframe_workflow_mcp/toolbox/contract.py`](../mainframe_workflow_mcp/toolbox/contract.py) |
| z/OSMF HTTP via the Zowe Python SDK | [`mainframe_workflow_mcp/clients/zowe_sdk.py`](../mainframe_workflow_mcp/clients/zowe_sdk.py) |
| SQLite action log | [`mainframe_workflow_mcp/db.py`](../mainframe_workflow_mcp/db.py) |
| Zowe vault → host/user/password | [`mainframe_workflow_mcp/credentials.py`](../mainframe_workflow_mcp/credentials.py) and [`credential-resolver/`](../credential-resolver/) |

## Folder map

```
mainframe_workflow_mcp/   Python MCP server (this product)
credential-resolver/      Node helper: reads the OS vault Zowe already uses
tests/                    pytest suite
docs/architecture.md      this file
```

The z/OSMF tool surface lives in `mainframe_workflow_mcp/toolbox/` — a reference implementation that ships with the repo, so a fresh clone runs with no private access. `mainframe_workflow_mcp/_toolbox.py` resolves it: if the private `zcrafter-mainframe-mcp` package is installed it is used instead, otherwise the bundled one is.

## Approval: what bridge does and doesn't do

Every tool in `toolbox/contract.py` carries an `approval` field: `"never"` for reads, `"required"` for anything that changes z/OS state. `proxy.py` reads this flag only to validate it's one of the two known values — it does not branch behavior on it. Every call bridge receives is executed and logged; bridge has no concept of a pending or unapproved call.

This is deliberate: the human-in-the-loop gate is backend's approval-gate state (a correlated pending-action REST POST to the CLI, per ZCrafter's target architecture), which happens *before* backend ever calls bridge for a `"required"` tool. Bridge exposing the flag lets backend know which tools need that gate without bridge having to enforce it twice. Earlier versions of this repo had bridge run its own spec/plan approval workflow in front of mutating tools; that's been removed in favor of this single gate living in backend.

## Action log

`db.py`'s `ActionLogStore` records one row per tool call: tool name, a human-readable target, status, a short summary, sanitized input (secrets redacted, diffs hashed, bulk content truncated via `toolbox/action_log.py`'s `_sanitize_action_input`), and a timestamp. It's an audit trail, not a content store — never job/member/dataset content, never credentials.

## Credentials

Resolved once per executor build: Python runs `credential-resolver/dist/resolver.js`, which prints a JSON profile to stdout by reading the same vault Zowe's own CLI uses. Nothing from the vault is written to disk by bridge.
