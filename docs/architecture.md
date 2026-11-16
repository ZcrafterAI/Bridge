# Architecture

This is the developer map for **Mainframe Workflow MCP**. Users should start at the [README](../README.md). Contributors should start at [CONTRIBUTING.md](../CONTRIBUTING.md), then this file.

## Where to look first

| If you want to understand… | Open |
|---|---|
| Tools the agent actually calls | [`mainframe_workflow_mcp/server.py`](../mainframe_workflow_mcp/server.py) |
| Spec/plan approval rules | [`mainframe_workflow_mcp/requests.py`](../mainframe_workflow_mcp/requests.py) |
| How a person approves | [`mainframe_workflow_mcp/approval.py`](../mainframe_workflow_mcp/approval.py), terminal command in [`approve.py`](../mainframe_workflow_mcp/approve.py) |
| What a plan step is and how a call is matched to one | [`mainframe_workflow_mcp/plan_steps.py`](../mainframe_workflow_mcp/plan_steps.py) |
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
   ├─ approval broker (the person's yes: client prompt, browser page, or terminal)
   └─ proxied zcrafter tools
          │  read-only → pass through
          │  mutating  → require request_id with an approved plan,
          │              and a plan step this call matches
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
| `SPEC_APPROVED` | the person approves after `approve_spec` asks them | Draft a plan |
| `PLAN_DRAFT` | `draft_plan` with its steps | Same; plan is not approved yet |
| `PLAN_APPROVED` | the person approves after `approve_plan` asks them | The plan's steps, with this `request_id` |
| `EXECUTING` | first step run after plan approval | The steps that are left, until `complete_request` |

Editing an approved spec (`draft_spec` again) drops the request back to `SPEC_DRAFT` and clears any plan approval. Same idea for editing an approved plan.

## Approval

`approve_spec` and `approve_plan` are requests for an approval, not approvals. The agent's call makes the broker (`approval.py`) ask the person, and only the person's answer moves the phase. `RequestManager.approve_spec` / `approve_plan` record that answer and are never reachable from a tool without it.

The broker asks in this order (`MAINFRAME_WORKFLOW_APPROVAL=auto`):

1. **The AI client's own prompt** (MCP elicitation), when the client declares it. On protocol versions before 2026-07-28 the server asks during the call (`ctx.elicit`). From 2026-07-28 a server can no longer ask mid-call, so the tool returns `InputRequiredResult` and the client calls it again with the person's answer; the answer counts only for the request, kind and version it was asked about (`request_state`).
2. **A page on this machine.** The broker starts an HTTP server on `127.0.0.1` on a free port and opens `/approval/<id>?t=<token>` in the person's browser. The token is random, stored only as a hash, and is never part of any tool result, so the agent cannot build the address. The page answers only to a local `Host`, refuses a POST from another origin, and takes one answer.
3. **A terminal.** `python -m mainframe_workflow_mcp.approve` reads the pending approvals from the store and asks at a TTY. It refuses to run with piped input.

A tool call waits `MAINFRAME_WORKFLOW_APPROVAL_WAIT_SECONDS` for the page or the terminal, then returns `WAITING_FOR_PERSON`; the approval stays open and the next call picks up the answer. An answer belongs to one revision: a rejected revision stays rejected, and an edit makes a new revision that must be asked about again.

What this does not defend against: an agent that has a shell on the same machine as the server can read the store or the server's log, or call z/OSMF itself. Run Bridge where the agent has only the MCP connection if that matters to you.

## Plan steps

A plan carries `steps`, each `{tool, args, times}` (`plan_steps.py`). `draft_plan` validates them against the tool catalog: the tool must be a mutating one, the step must name every required argument that is not bulk content, and the target must not be protected. They are stored with the plan revision (`plan_revisions.steps_json`).

A mutating call runs only when `find_step` finds a step of the approved revision that matches and has a use left (`plan_step_uses`):

- every argument the step names must be equal in the call (dataset, member and job names case-insensitively, everything else exactly);
- the call may not carry an argument the step did not name, except content the step left open (`content`, `unifiedDiff`, `attributes`), which the approval told the person was not fixed;
- `job.submit` never has open content: a step that submits from a dataset cannot be used to send other JCL;
- a call that fails does not use up its step.

A plan approved before steps existed has none, so it allows nothing until it is redrafted.

## Other guards

- `MAINFRAME_WORKFLOW_READ_ONLY=true`: mutating tools are not registered.
- `MAINFRAME_WORKFLOW_PROTECTED_DATASETS`: patterns (`*` one qualifier, `**` any) no dataset or member tool may write to. It does not read inside a TSO or console command; those are approved word for word by the person instead.
- `tso.query` takes only listing commands and refuses operands that write a dataset (`clients/tso.py`). `tso.command` refuses SUBMIT and anything with a line break.
- The z/OSMF client is built on first use (`_LazyClient` in `server.py`), so the server starts without a Zowe profile and the first tool call explains what is missing.

Defaults: abandon idle `ACTIVE` requests after 14 days; archive abandoned/completed rows after 90 days (`MAINFRAME_WORKFLOW_IDLE_DAYS`, `MAINFRAME_WORKFLOW_RETENTION_DAYS`).
