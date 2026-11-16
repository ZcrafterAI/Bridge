"""Approve or reject waiting requests from a terminal.

    zcrafter-bridge approve          (from a checkout: python -m mainframe_workflow_mcp.approve)

For machines with no browser (a server reached over SSH). It asks a person at a keyboard, so
it refuses to run when its input is not a terminal: an agent's shell cannot answer for you.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from . import config
from .approval import approval_subject, approval_text
from .db import RequestStore


def main() -> int:
    if not sys.stdin.isatty():
        print("This must be run by a person in a terminal.", file=sys.stderr)
        return 2
    store = RequestStore(config.DB_PATH)
    pending = store.list_pending_approvals()
    if not pending:
        print("Nothing is waiting for approval.")
        return 0
    for row in pending:
        subject = approval_subject(store, row["request_id"], row["kind"], row["version"])
        print("\n" + "=" * 72)
        print(approval_text(subject))
        print("=" * 72)
        answer = input("Approve? [y = approve, n = reject, Enter = skip] ").strip().lower()
        if answer not in {"y", "yes", "n", "no"}:
            print("Skipped.")
            continue
        status = "APPROVED" if answer in {"y", "yes"} else "REJECTED"
        now = datetime.now(timezone.utc).isoformat()
        if store.decide_approval(row["id"], status, "the terminal", now=now):
            print(status.capitalize() + ".")
        else:
            print("This was answered somewhere else first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
