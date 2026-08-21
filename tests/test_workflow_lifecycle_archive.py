from datetime import datetime, timedelta, timezone
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.lifecycle import archive_sweep

def test_archive_sweep_exports_and_prunes_old_completed_requests(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    old_touch = (now - timedelta(days=100)).isoformat()

    store.create_request("req-old", "add a field to CUSTREC", now=old_touch)
    store.add_clarification("req-old", "which dataset?", "IBMUSER.COBOL.SRC", now=old_touch)
    store.add_spec_revision("req-old", 1, "# Spec content", now=old_touch)
    store.add_plan_revision("req-old", 1, "# Plan content", now=old_touch)
    store.add_action_log(
        request_id="req-old", tool="dataset.read", target="HLQ.SRC", status="ok",
        summary="dataset.read completed.", input_json="{}", diff_hash=None, now=old_touch,
    )
    store.update_phase_status("req-old", status="COMPLETED", now=old_touch)

    archive_dir = tmp_path / "archive"
    archived = archive_sweep(store, archive_dir, retention_days=90, now=now)

    assert archived == ["req-old"]
    assert store.get_request("req-old") is None

    archive_file = archive_dir / "req-old.md"
    assert archive_file.exists()
    content = archive_file.read_text(encoding="utf-8")
    assert "add a field to CUSTREC" in content
    assert "which dataset?" in content
    assert "# Spec content" in content
    assert "# Plan content" in content
    assert "dataset.read" in content
    store.close()

def test_archive_sweep_leaves_recent_completed_requests(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    recent_touch = (now - timedelta(days=10)).isoformat()
    store.create_request("req-recent", "a", now=recent_touch)
    store.update_phase_status("req-recent", status="COMPLETED", now=recent_touch)

    archived = archive_sweep(store, tmp_path / "archive", retention_days=90, now=now)

    assert archived == []
    assert store.get_request("req-recent") is not None
    store.close()

def test_archive_sweep_ignores_active_requests_regardless_of_age(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    old_touch = (now - timedelta(days=200)).isoformat()
    store.create_request("req-active", "a", now=old_touch)

    archived = archive_sweep(store, tmp_path / "archive", retention_days=90, now=now)

    assert archived == []
    assert store.get_request("req-active") is not None
    store.close()
