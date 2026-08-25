# Architecture

This is the developer map for **Mainframe Workflow MCP**. Users should start at the [README](../README.md). Contributors should start at [CONTRIBUTING.md](../CONTRIBUTING.md), then this file.

## Where to look first

| If you want to understand… | Open |
|---|---|
| Tools the agent actually calls | [`mainframe_workflow_mcp/server.py`](../mainframe_workflow_mcp/server.py) |
| Spec/plan approval rules | [`mainframe_workflow_mcp/requests.py`](../mainframe_workflow_mcp/requests.py) |
| How zcrafter tools are wrapped | [`mainframe_workflow_mcp/proxy.py`](../mainframe_workflow_mcp/proxy.py) |
| z/OSMF HTTP via the Zowe Python SDK | [`mainframe_workflow_mcp/clients/zowe_sdk.py`](../mainframe_workflow_mcp/clients/zowe_sdk.py) |
| SQLite request store + audit log | [`mainframe_workflow_mcp/db.py`](../mainframe_workflow_mcp/db.py) |
| Idle abandon / archive | [`mainframe_workflow_mcp/lifecycle.py`](../mainframe_workflow_mcp/lifecycle.py) |
| Zowe vault → host/user/password | [`mainframe_workflow_mcp/credentials.py`](../mainframe_workflow_mcp/credentials.py) and [`credential-resolver/`](../credential-resolver/) |
| Agent instructions for the gate | [`.claude/skills/mainframe-workflow/SKILL.md`](../.claude/skills/mainframe-workflow/SKILL.md) |

## Folder map

```
mainframe_workflow_mcp/   Python MCP server (this product)
credential-resolver/      Node helper: reads the OS vault Zowe already uses
tests/                    pytest suite for the workflow server
scripts/                  optional live z/OSMF smoke script
.claude/skills/           companion skill that teaches the agent the gate
docs/architecture.md      this file
```

The z/OSMF tool surface lives in `mainframe_workflow_mcp/toolbox/` — a reference implementation that ships with the repo, so a fresh clone runs with no private access. `mainframe_workflow_mcp/_toolbox.py` resolves it: if the private `zcrafter-mainframe-mcp` package is installed it is used instead, otherwise the bundled one is. Either way this server auto-registers the tools and adds the request gate on top.

## Runtime flow

```
Agent host
   │
   ▼
mainframe_workflow_mcp
   ├─ request tools (start / clarify / spec / plan / approve / complete)
   ├─ SQLite store (requests, revisions, action log)
   └─ proxied zcrafter tools
          │  read-only → pass through
          │  mutating  → require request_id with an approved plan
          ▼
   zcrafter_mainframe (private library)
          ▼
   Zowe Python SDK → z/OSMF → your z/OS system
```

Credentials are resolved once at startup: Python runs `credential-resolver/dist/resolver.js`, which prints a JSON profile to stdout. Nothing from the vault is written to disk.

## Request lifecycle (internal names)

Every request has a **phase** (where it is in the workflow) and a **status** (`ACTIVE`, `ABANDONED`, or `COMPLETED`).

| Phase | How you get here | What the agent may do |
|---|---|---|
| `CLARIFYING` | `start_request` | Ask questions; use read-only tools |
| `SPEC_DRAFT` | `draft_spec` | Same, plus a spec is on file |
| `SPEC_APPROVED` | `approve_spec` after an explicit user yes | Draft a plan |
| `PLAN_DRAFT` | `draft_plan` | Same; plan is not approved yet |
| `PLAN_APPROVED` | `approve_plan` after an explicit user yes | Mutating tools with this `request_id` |
| `EXECUTING` | first mutating call after plan approval | Continue until `complete_request` |

Editing an approved spec (`draft_spec` again) drops the request back to `SPEC_DRAFT` and clears any plan approval. Same idea for editing an approved plan.

`approve_spec` and `approve_plan` must only be called after a clear yes in the **current** chat turn. The server does not try to prove a human clicked a button; the companion skill plus the MCP host’s own permission prompts are the control.

Defaults: abandon idle `ACTIVE` requests after 14 days; archive abandoned/completed rows after 90 days (`MAINFRAME_WORKFLOW_IDLE_DAYS`, `MAINFRAME_WORKFLOW_RETENTION_DAYS`).
