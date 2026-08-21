from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .db import RequestStore


def idle_sweep(store: RequestStore, idle_days: int, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=idle_days)).isoformat()
    abandoned_ids = []
    for request in store.list_requests(status="ACTIVE"):
        if request["updated_at"] < cutoff:
            store.update_phase_status(
                request["id"], status="ABANDONED", cancel_reason="idle timeout", now=now.isoformat(),
            )
            abandoned_ids.append(request["id"])
    return abandoned_ids


def archive_sweep(store: RequestStore, archive_dir: Path, retention_days: int, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived_ids = []
    for status in ("ABANDONED", "COMPLETED"):
        for request in store.list_requests(status=status):
            if request["updated_at"] >= cutoff:
                continue
            _write_archive_file(store, archive_dir, request)
            store.delete_request_cascade(request["id"])
            archived_ids.append(request["id"])

    if archived_ids:
        store.vacuum()
    return archived_ids


def _write_archive_file(store: RequestStore, archive_dir: Path, request: dict) -> None:
    clarifications = store.list_clarifications(request["id"])
    spec = store.latest_spec_revision(request["id"])
    plan = store.latest_plan_revision(request["id"])
    actions = store.list_action_log(request["id"])

    lines = [
        f"# Request {request['id']}",
        "",
        f"- Status: {request['status']}",
        f"- Phase: {request['phase']}",
        f"- Created: {request['created_at']}",
        f"- Updated: {request['updated_at']}",
        f"- Spec approved: {request['spec_approved_at'] or '_not approved_'} (version {request['spec_approved_version']})",
        f"- Plan approved: {request['plan_approved_at'] or '_not approved_'} (version {request['plan_approved_version']})",
        "",
        "## Raw request",
        "",
        request["raw_request"],
        "",
        "## Clarifications",
        "",
    ]
    for c in clarifications:
        lines += [f"**Q:** {c['question']}", f"**A:** {c['answer']}", ""]

    lines += ["## Final spec", "", spec["content"] if spec else "_none_", ""]
    lines += ["## Final plan", "", plan["content"] if plan else "_none_", ""]
    lines += ["## Action log", ""]
    for a in actions:
        lines.append(f"- `{a['created_at']}` **{a['tool']}** -> {a['status']}: {a['summary']}")

    (archive_dir / f"{request['id']}.md").write_text("\n".join(lines), encoding="utf-8")
