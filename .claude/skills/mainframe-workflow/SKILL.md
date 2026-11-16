---
name: mainframe-workflow
description: Use for any mainframe-related user request (datasets, members, z/OS UNIX files, jobs, JCL, TSO, console, z/OS) — routes it through mainframe_workflow_mcp's clarify, spec-approval, and plan-approval gate before any mutating mainframe tool is used.
---

# Mainframe Workflow

`mainframe_workflow_mcp` is the only connected tool surface for mainframe
work. It hard-gates every tool that changes z/OS behind a request whose spec
and plan a person approved (see `docs/architecture.md`).

## When this applies

Any user request touching datasets, PDS/PDSE members, z/OS UNIX files, jobs,
JCL, TSO or operator commands, or z/OSMF.

**Reads need no request.** Call read-only tools directly and answer. Open a
request only when something will change on z/OS.

**Habits.** `profileName` is optional; leave it out. Reads accept
`searchText`/`maxLines`/`regex`: search a large log rather than reading it back
whole, and if a result says `truncated`, say so. For a failed job, start with
`job.failed` and `job.steps` to find the step, then search its output.
`tso.query` runs read-only TSO commands (LISTCAT, LISTDS, LISTUSER...) with no
request; any other TSO command is `tso.command`, which is gated.

## The flow

1. **Start.** Call `start_request(raw_request)` with the user's ask as given.
   Keep the returned `request_id` for every following call in this thread.
2. **Clarify.** Ask the user whatever questions you genuinely need answered
   to understand the request — one at a time is fine. Log each pair with
   `record_clarification(request_id, question, answer)`.
3. **Spec.** Call `draft_spec(request_id, content)` with a concise spec: what
   changes, why, and what "done" looks like. Read-only tools are available any
   time to ground the spec in the real system. Present the spec in chat, then
   call `approve_spec(request_id)`.
4. **Plan.** Call `draft_plan(request_id, content, steps)`. `steps` lists
   every change, one object per mutating call:

   ```json
   [
     {"tool": "member.patch", "args": {"dataset": "PAY.TEST.COBOL", "member": "PAYCALC", "unifiedDiff": "..."}},
     {"tool": "job.submit", "args": {"dataset": "PAY.TEST.JCL(PAYRUN)"}, "times": 2}
   ]
   ```

   Each step names its target (dataset, member, path, job id, or the exact
   command). Put `content`, `unifiedDiff` or `jcl` in the step whenever you
   already know the exact text: the person then approves exactly that. Use
   `"times"` when a step must run more than once. List only changes; reads
   need no step. Present the plan in chat, then call `approve_plan(request_id)`.
5. **Execute.** Call the mutating tools with `request_id`. A call runs only if
   it matches a step of the approved plan, and each step runs as many times as
   it says.
6. **Close out.** Call `complete_request(request_id)` once the work is done,
   or `cancel_request(request_id, reason)` if the user drops the request.

## Approval is the person's, not yours

`approve_spec` and `approve_plan` do not approve anything. They make the
server ask the person directly (in their AI client's prompt, a browser page,
or a terminal) and return the person's answer.

- `WAITING_FOR_PERSON`: the person has not answered. Tell them an approval is
  waiting, then call the same tool again. Do not try another route.
- `REJECTED`: ask what they want changed, write a new revision, and ask
  again. The same revision will not be approved.

## When a change is refused

- `PLAN_NOT_APPROVED`: a step above was skipped, or the plan was edited after
  approval. Get the approval.
- `STEP_NOT_IN_PLAN`: this change is not a step of the approved plan, or its
  step was already used. Do not rephrase the call to slip through. Draft a new
  plan revision that lists the change and ask the person to approve it.
- `PROTECTED_DATASET`: this server refuses changes to that dataset. Tell the
  user; there is no way around it from here.
- `INVALID_PLAN_STEPS`: fix the step the message names and draft the plan again.

## Rules

- Never tell the user a change is approved until the tool returns the
  approved phase.
- Editing a spec after approval un-approves it *and* any approved plan.
  Editing a plan un-approves the plan. Re-present and ask again.
- `get_request_status(request_id)` shows the phase, the plan's steps and which
  steps are left.
