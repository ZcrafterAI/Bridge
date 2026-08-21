---
name: mainframe-workflow
description: Use for any mainframe-related user request (datasets, members, jobs, JCL, z/OS) — routes it through mainframe_workflow_mcp's clarify, spec-approval, and plan-approval gate before any mutating mainframe tool is used.
---

# Mainframe Workflow

`mainframe_workflow_mcp` is the only connected tool surface for mainframe
work. It wraps the zcrafter mainframe toolbox and hard-gates mutating calls
behind a request that has an approved spec and an approved plan (see
`docs/architecture.md`).

## When this applies

Any user request touching datasets, PDS/PDSE members, jobs, JCL, or z/OSMF —
whether read-only investigation or an actual change.

## The flow

1. **Start.** Call `start_request(raw_request)` with the user's ask as given.
   Keep the returned `request_id` for every following call in this thread.
2. **Clarify.** Ask the user whatever questions you genuinely need answered
   to understand the request — one at a time is fine. Log each pair with
   `record_clarification(request_id, question, answer)`. This step has no
   approval gate; use judgment about when you have enough to draft a spec.
3. **Spec.** Call `draft_spec(request_id, content)` with a concise spec: what
   changes, why, and what "done" looks like. Read-only zcrafter tools
   (`dataset.read`, `member.list`, `job.output`, etc.) are available any time
   during this step to ground the spec in the real system — they never need
   a `request_id`. Present the spec in chat and ask the user to approve it
   explicitly. **Only after an explicit yes in the current turn**, call
   `approve_spec(request_id)`. Never call it speculatively or infer approval
   from silence or an unrelated reply.
4. **Plan.** Call `draft_plan(request_id, content)` — this only succeeds once
   the spec is approved. Present the plan the same way, wait for explicit
   approval, then call `approve_plan(request_id)`.
5. **Execute.** Mutating zcrafter tools (`member.patch`, `dataset.write`,
   `job.submit`, etc.) now succeed for this `request_id` — pass it as the
   `request_id` argument on every such call. If the server returns
   `{"status": "error", "error": {"code": "PLAN_NOT_APPROVED", ...}}` or
   `"REQUEST_NOT_FOUND"`, that means a step above was skipped or the wrong
   `request_id` was used — do not retry with `approved` or similar fields;
   there are none to set. Fix the actual gap (get approval, or use the right id).
6. **Close out.** Call `complete_request(request_id)` once the work is done,
   or `cancel_request(request_id, reason)` if the user drops the request
   before finishing.

## Rules

- Never call `approve_spec` or `approve_plan` without an explicit yes from
  the user in the same turn. These calls are the only thing standing between
  a drafted plan and a live mainframe change.
- Editing a spec after approval (calling `draft_spec` again) un-approves it
  *and* any already-approved plan — re-present and re-approve both if that
  happens.
- `get_request_status(request_id)` and `list_requests(status=...)` are
  available any time to check where a request stands.
